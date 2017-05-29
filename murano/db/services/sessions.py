#    Copyright (c) 2013 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from castellan.common import exception as castellan_exception
from castellan.common.objects import opaque_data
from castellan.common import utils as castellan_utils
from castellan import key_manager

from murano.common import exceptions
from murano.db import models
from murano.db import session as db_session
from murano.services import actions
from murano.services import states

from oslo_config import cfg
from oslo_utils import uuidutils

from oslo_log import log as logging

import json


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class SessionServices(object):
    @staticmethod
    def get_sessions(environment_id, state=None):
        """Get list of sessions for specified environment.

        :param environment_id: Environment Id
        :param state: murano.services.states.EnvironmentStatus
        :return: Sessions for specified Environment, if SessionState is
        not defined all sessions for specified environment is returned.
        """

        unit = db_session.get_session()
        # Here we duplicate logic for reducing calls to database
        # Checks for validation is same as in validate.
        query = unit.query(models.Session).filter(
            # Get all session for this environment
            models.Session.environment_id == environment_id,
            # Only sessions with same version as current env version are valid
        )

        if state:
            # in this state, if state is not specified return in all states
            query = query.filter(models.Session.state == state)

        return query.order_by(models.Session.version.desc(),
                              models.Session.updated.desc()).all()

    @staticmethod
    def get(session_id):
        unit = db_session.get_session()
        session = unit.query(models.Session).get(session_id)
        if (uuidutils.is_uuid_like(session.description) and
                CONF.murano.encrypt_data is False):
            raise exceptions.SessionLoadException(session_id=session_id)
        if (uuidutils.is_uuid_like(session.description) is False and
                CONF.murano.encrypt_data):
            LOG.warning("CONF.murano.encrypt_data is True, but "
                        "session with id '{}' looks to be "
                        "unencrypted.".format(session_id))
            return session
        if CONF.murano.encrypt_data:
            context = castellan_utils.credential_factory(conf=CONF)
            manager = key_manager.API()
            try:
                description = manager.get(context,
                                          session.description).get_encoded()
            except castellan_exception.KeyManagerError as e:
                LOG.exception(e)
                raise
            session.description = json.loads(description)
        return session

    @staticmethod
    def save(session):
        if CONF.murano.encrypt_data:
            manager = key_manager.API()
            context = castellan_utils.credential_factory(conf=CONF)
            description_bytes = opaque_data.OpaqueData(
                bytes(json.dumps(session.description)))
            try:
                stored_key_id = manager.store(context, description_bytes)
            except castellan_exception.KeyManagerError as e:
                LOG.exception(e)
                raise
            session.description = stored_key_id
        unit = db_session.get_session()
        with unit.begin():
            unit.add(session)

    @staticmethod
    def create(environment_id, user_id):
        """Creates session object for specific environment for specified user.

        :param environment_id: Environment Id
        :param user_id: User Id
        :return: Created session
        """
        unit = db_session.get_session()
        environment = unit.query(models.Environment).get(environment_id)

        session = models.Session()
        session.environment_id = environment.id
        session.user_id = user_id
        session.state = states.SessionState.OPENED
        # used for checking if other sessions was deployed before this one
        session.version = environment.version
        # all changes to environment is stored here, and translated to
        # environment only after deployment completed
        session.description = environment.description

        with unit.begin():
            unit.add(session)

        return session

    @staticmethod
    def validate(session):
        """Validates session

        Session is valid only if no other session for same.
        environment was already deployed on in deploying state,

        :param session: Session for validation
        """

        # if other session is deploying now current session is invalid
        unit = db_session.get_session()

        # if environment version is higher than version on which current
        #  session is created then other session was already deployed
        current_env = unit.query(models.Environment).\
            get(session.environment_id)
        if current_env.version > session.version:
            return False

        # if other session is deploying now current session is invalid
        other_is_deploying = unit.query(models.Session).filter_by(
            environment_id=session.environment_id,
            state=states.SessionState.DEPLOYING
        ).count() > 0
        if session.state == states.SessionState.OPENED and other_is_deploying:
            return False

        return True

    @staticmethod
    def deploy(session, environment, unit, context):
        """Prepares and deployes environment

        Prepares environment for deployment and send deployment command to
        orchestration engine

        :param session: session that is going to be deployed
        :param unit: SQLalchemy session
        :param token: auth token that is going to be used by orchestration
        """

        deleted = session.description['Objects'] is None
        action_name = None if deleted else 'deploy'
        actions.ActionServices.submit_task(
            action_name, environment.id,
            {}, environment, session,
            context, unit)
