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
import json
import mock

from murano.common import exceptions
from murano.db import models
from murano.db.services import sessions
from murano.tests.unit import base
from murano.tests.unit import utils


class TestSessionsServices(base.MuranoWithDBTestCase):
    def setUp(self):
        super(TestSessionsServices, self).setUp()
        self.session = models.Session()
        self.encrypted_session = models.Session(
            description='fbf1a508-9d55-408d-a186-baf7a9174058')

        self.env_services = sessions.SessionServices()
        self.dummy_context = utils.dummy_context()

    @mock.patch('murano.db.services.sessions.key_manager')
    @mock.patch('murano.db.services.sessions.db_session')
    @mock.patch('murano.db.services.sessions.LOG')
    def test_get_unencrypted_encrypt_data_off(self, mock_log, mock_db_session,
                                              mock_key_manager):
        mock_db_session.get_session().query().get.return_value =\
            self.session
        self.override_config('encrypt_data', False, 'murano')
        self.env_services.get(self.session.id)
        mock_log.warning.assert_not_called()
        mock_key_manager.get.assert_not_called()

    @mock.patch('murano.db.services.sessions.key_manager')
    @mock.patch('murano.db.services.sessions.db_session')
    @mock.patch('murano.db.services.sessions.LOG')
    def test_get_unencrypted_encrypt_data_on(self, mock_log, mock_db_session,
                                             mock_key_manager):
        mock_db_session.get_session().query().get.return_value =\
            self.session
        self.override_config('encrypt_data', True, 'murano')
        self.env_services.get(self.session.id)
        mock_log.warning.assert_called_with(
            "CONF.murano.encrypt_data is True, but session with id "
            "'{}' looks to be unencrypted.".format(self.session.id))
        mock_key_manager.get.assert_not_called()

    @mock.patch('murano.db.services.sessions.key_manager')
    @mock.patch('murano.db.services.sessions.db_session')
    @mock.patch('murano.db.services.sessions.LOG')
    def test_get_encrypted_encrypt_data_off(self, mock_log, mock_db_session,
                                            mock_key_manager):
        mock_db_session.get_session().query().get.return_value =\
            self.encrypted_session
        self.override_config('encrypt_data', False, 'murano')
        self.assertRaises(exceptions.SessionLoadException,
                          self.env_services.get, self.encrypted_session.id)

    @mock.patch('murano.db.services.sessions.castellan_utils')
    @mock.patch('murano.db.services.sessions.key_manager')
    @mock.patch('murano.db.services.sessions.db_session')
    @mock.patch('murano.db.services.sessions.LOG')
    def test_get_encrypted_encrypt_data_on(self, mock_log, mock_db_session,
                                           mock_key_manager,
                                           mock_castellan_utils):
        encrypted_description = self.encrypted_session.description
        mock_db_session.get_session().query().get.return_value =\
            self.encrypted_session
        mock_key_manager.API().get.return_value.get_encoded.return_value =\
            json.dumps({})
        mock_castellan_utils.credential_factory.return_value =\
            self.dummy_context
        self.override_config('encrypt_data', True, 'murano')

        self.env_services.get(self.encrypted_session.id)

        mock_key_manager.API().get.assert_called_once_with(
            self.dummy_context, encrypted_description)

    @mock.patch('murano.db.services.sessions.key_manager')
    @mock.patch('murano.db.services.sessions.db_session')
    def test_save_encrypt_data_off(self, mock_db_session, mock_key_manager):
        self.override_config('encrypt_data', False, 'murano')
        self.env_services.save(self.encrypted_session)
        mock_key_manager.API().store.assert_not_called()
        mock_db_session.get_session().add.assert_called_once_with(
            self.encrypted_session)

    @mock.patch('murano.db.services.sessions.opaque_data')
    @mock.patch('murano.db.services.sessions.key_manager')
    @mock.patch('murano.db.services.sessions.castellan_utils')
    @mock.patch('murano.db.services.sessions.db_session')
    def test_save_encrypt_data_on(self, mock_db_session, mock_castellan_utils,
                                  mock_key_manager, mock_opaque_data):
        self.override_config('encrypt_data', True, 'murano')
        mock_castellan_utils.credential_factory.return_value =\
            self.dummy_context
        mock_data = mock.MagicMock()
        mock_opaque_data.OpaqueData.return_value = mock_data

        self.env_services.save(self.encrypted_session)

        mock_key_manager.API().store.assert_called_once_with(
            self.dummy_context, mock_data)
        mock_db_session.get_session().add.assert_called_once_with(
            self.encrypted_session)
