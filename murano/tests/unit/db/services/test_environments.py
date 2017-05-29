#    Copyright (c) 2015 Mirantis, Inc.
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
import datetime as dt
import json
import mock
import uuid

from oslo_utils import timeutils

from murano.common import exceptions
from murano.db import models
from murano.db.services import environments
from murano.db import session as db_session
from murano.services import states
from murano.tests.unit import base
from murano.tests.unit import utils

OLD_VERSION = 0
LATEST_VERSION = 1


class TestEnvironmentServices(base.MuranoWithDBTestCase):
    def setUp(self):
        super(TestEnvironmentServices, self).setUp()
        self.environment = models.Environment(
            name='test_environment', tenant_id='test_tenant_id',
            version=LATEST_VERSION
        )
        self.encrypted_environment = models.Environment(
            name='test_environment', tenant_id='test_tenant_id',
            version=LATEST_VERSION,
            description='fbf1a508-9d55-408d-a186-baf7a9174058'
        )

        self.env_services = environments.EnvironmentServices()
        self.dummy_context = utils.dummy_context()

    def test_environment_ready_if_last_session_deployed_after_failed(self):
        """Test environment ready status

        If last session was deployed successfully and other session
        was failed - environment must have status "ready".

        Bug: #1413260
        """

        session = db_session.get_session()

        session.add(self.environment)

        now = timeutils.utcnow()

        session_1 = models.Session(
            environment=self.environment, user_id='test_user_id_1',
            version=OLD_VERSION,
            state=states.SessionState.DEPLOY_FAILURE,
            updated=now, description={}
        )
        session_2 = models.Session(
            environment=self.environment, user_id='test_user_id_2',
            version=LATEST_VERSION,
            state=states.SessionState.DEPLOYED,
            updated=now + dt.timedelta(minutes=1), description={}
        )
        session.add_all([session_1, session_2])
        session.flush()

        expected_status = states.EnvironmentStatus.READY
        actual_status = environments.EnvironmentServices.get_status(
            self.environment.id
        )

        self.assertEqual(expected_status, actual_status)

    @mock.patch("murano.db.services.environments.auth_utils")
    def test_get_network_driver(self, mock_authentication):
        self.tenant_id = str(uuid.uuid4())
        self.context = utils.dummy_context(tenant_id=self.tenant_id)

        driver_context = self.env_services.get_network_driver(self.context)
        self.assertEqual(driver_context, "neutron")

    def test_get_status(self):
        session = db_session.get_session()

        session.add(self.environment)

        now = timeutils.utcnow()

        session_1 = models.Session(
            environment=self.environment, user_id='test_user_id_1',
            version=OLD_VERSION,
            state=states.SessionState.DEPLOY_FAILURE,
            updated=now, description={}
        )

        session.add(session_1)
        session.flush()

        expected_status = states.EnvironmentStatus.DEPLOY_FAILURE
        self.assertEqual(expected_status, self.env_services.get_status(
            self.environment.id))

    def test_delete_failure_get_description(self):
        session = db_session.get_session()

        session.add(self.environment)

        now = timeutils.utcnow()

        session_1 = models.Session(
            environment=self.environment, user_id='test_user_id_1',
            version=OLD_VERSION,
            state=states.SessionState.DELETE_FAILURE,
            updated=now, description={}
        )

        session.add(session_1)
        session.flush()

        expected_status = states.EnvironmentStatus.DELETE_FAILURE
        self.assertEqual(expected_status, self.env_services.get_status(
            self.environment.id))

        env_id = self.environment.id
        description = (self.env_services.
                       get_environment_description(env_id,
                                                   session_id=None,
                                                   inner=False))
        self.assertEqual({}, description)

    @mock.patch('murano.db.services.environments.key_manager')
    @mock.patch('murano.db.services.environments.db_session')
    @mock.patch('murano.db.services.environments.LOG')
    def test_get_unencrypted_encrypt_data_off(self, mock_log, mock_db_session,
                                              mock_key_manager):
        mock_db_session.get_session().query().get.return_value =\
            self.environment
        self.override_config('encrypt_data', False, 'murano')
        self.env_services.get(self.environment.id)
        mock_log.warning.assert_not_called()
        mock_key_manager.get.assert_not_called()

    @mock.patch('murano.db.services.environments.key_manager')
    @mock.patch('murano.db.services.environments.db_session')
    @mock.patch('murano.db.services.environments.LOG')
    def test_get_unencrypted_encrypt_data_on(self, mock_log, mock_db_session,
                                             mock_key_manager):
        mock_db_session.get_session().query().get.return_value =\
            self.environment
        self.override_config('encrypt_data', True, 'murano')
        self.env_services.get(self.environment.id)
        mock_log.warning.assert_called_with(
            "CONF.murano.encrypt_data is True, but environment with id "
            "'{}' looks to be unencrypted.".format(self.environment.id))
        mock_key_manager.get.assert_not_called()

    @mock.patch('murano.db.services.environments.key_manager')
    @mock.patch('murano.db.services.environments.db_session')
    @mock.patch('murano.db.services.environments.LOG')
    def test_get_encrypted_encrypt_data_off(self, mock_log, mock_db_session,
                                            mock_key_manager):
        mock_db_session.get_session().query().get.return_value =\
            self.encrypted_environment
        self.override_config('encrypt_data', False, 'murano')
        self.assertRaises(exceptions.EnvironmentLoadException,
                          self.env_services.get, self.encrypted_environment.id)

    @mock.patch('murano.db.services.environments.castellan_utils')
    @mock.patch('murano.db.services.environments.key_manager')
    @mock.patch('murano.db.services.environments.db_session')
    @mock.patch('murano.db.services.environments.LOG')
    def test_get_encrypted_encrypt_data_on(self, mock_log, mock_db_session,
                                           mock_key_manager,
                                           mock_castellan_utils):
        encrypted_description = self.encrypted_environment.description
        mock_db_session.get_session().query().get.return_value =\
            self.encrypted_environment
        mock_key_manager.API().get.return_value.get_encoded.return_value =\
            json.dumps({})
        mock_castellan_utils.credential_factory.return_value =\
            self.dummy_context
        self.override_config('encrypt_data', True, 'murano')

        self.env_services.get(self.encrypted_environment.id)

        mock_key_manager.API().get.assert_called_once_with(
            self.dummy_context, encrypted_description)

    @mock.patch('murano.db.services.environments.key_manager')
    @mock.patch('murano.db.services.environments.db_session')
    def test_save_encrypt_data_off(self, mock_db_session, mock_key_manager):
        self.override_config('encrypt_data', False, 'murano')
        self.env_services.save(self.encrypted_environment)
        mock_key_manager.API().store.assert_not_called()
        mock_db_session.get_session().add.assert_called_once_with(
            self.encrypted_environment)

    @mock.patch('murano.db.services.environments.opaque_data')
    @mock.patch('murano.db.services.environments.key_manager')
    @mock.patch('murano.db.services.environments.castellan_utils')
    @mock.patch('murano.db.services.environments.db_session')
    def test_save_encrypt_data_on(self, mock_db_session, mock_castellan_utils,
                                  mock_key_manager, mock_opaque_data):
        self.override_config('encrypt_data', True, 'murano')
        mock_castellan_utils.credential_factory.return_value =\
            self.dummy_context
        mock_data = mock.MagicMock()
        mock_opaque_data.OpaqueData.return_value = mock_data

        self.env_services.save(self.encrypted_environment)

        mock_key_manager.API().store.assert_called_once_with(
            self.dummy_context, mock_data)
        mock_db_session.get_session().add.assert_called_once_with(
            self.encrypted_environment)
