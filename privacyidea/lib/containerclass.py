# (c) NetKnights GmbH 2024,  https://netknights.it
#
# This code is free software; you can redistribute it and/or
# modify it under the terms of the GNU AFFERO GENERAL PUBLIC LICENSE
# as published by the Free Software Foundation; either
# version 3 of the License, or any later version.
#
# This code is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU AFFERO GENERAL PUBLIC LICENSE for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-FileCopyrightText: 2024 Nils Behlen <nils.behlen@netknights.it>
# SPDX-FileCopyrightText: 2024 Jelina Unger <jelina.unger@netknights.it>
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
from datetime import datetime, timezone

from typing import List

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from flask import json

from privacyidea.lib import _
from privacyidea.lib.challenge import get_challenges
from privacyidea.lib.config import get_token_types
from privacyidea.lib.crypto import verify_ecc, decryptPassword
from privacyidea.lib.error import ParameterError, ResourceNotFoundError, TokenAdminError, privacyIDEAError
from privacyidea.lib.log import log_with
from privacyidea.lib.token import create_tokenclass_object, get_tokens, get_serial_by_otp_list, \
    get_tokens_from_serial_or_user
from privacyidea.lib.tokenclass import TokenClass
from privacyidea.lib.user import User
from privacyidea.models import (TokenContainerOwner, Realm, Token, db, TokenContainerStates,
                                TokenContainerInfo, TokenContainerRealm, TokenContainerTemplate)

log = logging.getLogger(__name__)


class TokenContainerClass:
    options = {}

    @log_with(log)
    def __init__(self, db_container):
        self._db_container = db_container
        # Create the TokenClass objects from the database objects
        token_list = []
        for t in db_container.tokens:
            token_object = create_tokenclass_object(t)
            if isinstance(token_object, TokenClass):
                token_list.append(token_object)

        self.tokens = token_list
        self.options = {}

    @classmethod
    def get_class_options(cls, only_selectable=False):
        """
        Returns the options for the container class.

        :param only_selectable: If True, only options with more than one value are returned.
        :return: Dictionary in the format {key: [values]}
        """
        if only_selectable:
            class_options = {key: values for key, values in cls.options.items() if len(values) > 1}
        else:
            class_options = cls.options
        return class_options

    def set_default_option(self, key):
        """
        Checks if a value is set in the container info for the requested key.
        If not, the default value is set, otherwise the already set value is kept.

        :param key: The key to be checked.
        :return: The used value for the key or None if the key does not exist in the class options.
        """
        class_options = self.get_class_options()
        key_options = class_options.get(key)

        if key_options is None:
            # The key does not exist in the class options
            return None

        # Check if value is already set for this key in the container info
        container_info = self.get_container_info_dict()
        value = container_info.get(key)
        if not value:
            # key not defined: set default value
            value = class_options[key][0]
            self.add_container_info(key, value)
        return value

    @property
    def serial(self):
        return self._db_container.serial

    @property
    def description(self):
        return self._db_container.description

    @description.setter
    def description(self, value: str):
        if not value:
            value = ""
        self._db_container.description = value
        self._db_container.save()

    @property
    def type(self):
        return self._db_container.type

    @property
    def last_authentication(self):
        """
        Returns the timestamp of the last seen field in the database.
        It is the time when a token of the container was last used successfully for authentication.
        From this layer on it is hence called 'last_authentication'.
        If the container was never used for authentication, the value is None.
        """
        last_auth = self._db_container.last_seen
        if last_auth:
            last_auth = last_auth.replace(tzinfo=timezone.utc)
        return last_auth

    def update_last_authentication(self):
        """
        Updates the timestamp of the last seen field in the database.
        """
        self._db_container.last_seen = datetime.now(timezone.utc)
        self._db_container.save()

    def reset_last_authentication(self):
        """
        Resets the timestamp of the last seen field in the database.
        """
        self._db_container.last_seen = None
        self._db_container.save()

    @property
    def last_synchronization(self):
        """
        Returns the timestamp of the last updated field in the database.
        It is the time when the container was last synchronized with the privacyIDEA server.
        From this layer on it is hence called 'last_synchronization'.
        """
        last_sync = self._db_container.last_updated
        if last_sync:
            last_sync = last_sync.replace(tzinfo=timezone.utc)
        return last_sync

    def update_last_synchronization(self):
        """
        Updates the timestamp of the last updated field in the database.
        """
        self._db_container.last_updated = datetime.now(timezone.utc)
        self._db_container.save()

    def reset_last_synchronization(self):
        """
        Resets the timestamp of the last updated field in the database.
        """
        self._db_container.last_updated = None
        self._db_container.save()

    @property
    def realms(self):
        return self._db_container.realms

    def set_realms(self, realms, add=False):
        """
        Set the realms of the container. If `add` is True, the realms will be added to the existing realms, otherwise
        the existing realms will be removed.

        :param realms: List of realm names
        :param add: False if the existing realms shall be removed, True otherwise
        :return: Dictionary in the format {realm: success}, the entry 'deleted' indicates whether existing realms were
                 deleted.
        """
        result = {}

        if not realms:
            realms = []

        # delete all container realms
        if not add:
            TokenContainerRealm.query.filter_by(container_id=self._db_container.id).delete()
            result["deleted"] = True
            self._db_container.save()

            # Check that user realms are kept
            user_realms = self._get_user_realms()
            missing_realms = list(set(user_realms).difference(realms))
            realms.extend(missing_realms)
            for realm in missing_realms:
                log.warning(
                    f"Realm {realm} can not be removed from container {self.serial} "
                    f"because a user from this realm is assigned th the container.")
        else:
            result["deleted"] = False

        for realm in realms:
            if realm:
                realm_db = Realm.query.filter_by(name=realm).first()
                if not realm_db:
                    result[realm] = False
                    log.warning(f"Realm {realm} does not exist.")
                else:
                    realm_id = realm_db.id
                    # Check if realm is already assigned to the container
                    if not TokenContainerRealm.query.filter_by(container_id=self._db_container.id,
                                                               realm_id=realm_id).first():
                        self._db_container.realms.append(realm_db)
                        result[realm] = True
                    else:
                        log.info(f"Realm {realm} is already assigned to container {self.serial}.")
                        result[realm] = False
        self._db_container.save()

        return result

    def _get_user_realms(self):
        """
        Returns a list of the realms of the users that are assigned to the container.
        """
        owners = self.get_users()
        realms = [owner.realm for owner in owners]
        return realms

    def remove_token(self, serial: str):
        """
        Remove a token from the container. Raises a ResourceNotFoundError if the token does not exist.

        :param serial: Serial of the token
        :return: True if the token was successfully removed, False if the token was not found in the container
        """
        token = Token.query.filter(Token.serial == serial).first()
        if not token:
            raise ResourceNotFoundError(f"Token with serial {serial} does not exist.")
        if token not in self._db_container.tokens:
            log.info(f"Token with serial {serial} not found in container {self.serial}.")
            return False

        self._db_container.tokens.remove(token)
        self._db_container.save()
        self.tokens = [t for t in self.tokens if t.get_serial() != serial]
        return True

    def add_token(self, token: TokenClass):
        """
        Add a token to the container.
        Raises a ParameterError if the token type is not supported by the container.

        :param token: TokenClass object
        :return: True if the token was successfully added, False if the token is already in the container
        """
        if token.get_type() not in self.get_supported_token_types():
            raise ParameterError(f"Token type {token.get_type()} not supported for container type {self.type}. "
                                 f"Supported types are {self.get_supported_token_types()}.")
        if token.get_serial() not in [t.get_serial() for t in self.tokens]:
            self.tokens.append(token)
            self._db_container.tokens = [t.token for t in self.tokens]
            self._db_container.save()
            return True
        return False

    def get_tokens(self):
        """
        Returns the tokens of the container as a list of TokenClass objects.
        """
        return self.tokens

    def delete(self):
        """
        Deletes the container and all associated objects from the database.
        """
        return self._db_container.delete()

    def add_user(self, user: User):
        """
        Assign a user to the container.
        Raises a UserError if the user does not exist.
        Raises a TokenAdminError if the container already has an owner.

        :param user: User object
        :return: True if the user was assigned
        """
        (user_id, resolver_type, resolver_name) = user.get_user_identifiers()
        if not self._db_container.owners.first():
            TokenContainerOwner(container_id=self._db_container.id,
                                user_id=user_id,
                                resolver=resolver_name,
                                realm_id=user.realm_id).save()
            # Add user realm to container realms
            realm_db = Realm.query.filter_by(name=user.realm).first()
            self._db_container.realms.append(realm_db)
            self._db_container.save()
            return True
        log.info(f"Container {self.serial} already has an owner.")
        raise TokenAdminError("This container is already assigned to another user.")

    def remove_user(self, user: User):
        """
        Remove a user from the container. Raises a ResourceNotFoundError if the user does not exist.

        :param user: User object to be removed
        :return: True if the user was removed, False if the user was not found in the container
        """
        (user_id, resolver_type, resolver_name) = user.get_user_identifiers()
        count = TokenContainerOwner.query.filter_by(container_id=self._db_container.id,
                                                    user_id=user_id,
                                                    resolver=resolver_name).delete()
        db.session.commit()
        return count > 0

    def get_users(self):
        """
        Returns a list of users that are assigned to the container.
        """
        db_container_owners: List[TokenContainerOwner] = TokenContainerOwner.query.filter_by(
            container_id=self._db_container.id).all()

        users: List[User] = []
        for owner in db_container_owners:
            realm = Realm.query.filter_by(id=owner.realm_id).first()
            user = User(uid=owner.user_id, realm=realm.name, resolver=owner.resolver)
            users.append(user)

        return users

    def get_states(self):
        """
        Returns the states of the container as a list of strings.
        """
        db_states = self._db_container.states
        states = [state.state for state in db_states]
        return states

    def _check_excluded_states(self, states):
        """
        Validates whether the state list contains states that excludes each other

        :param states: list of states
        :returns: True if the state list contains exclusive states, False otherwise
        """
        state_types = self.get_state_types()
        for state in states:
            if state in state_types:
                excluded_states = state_types[state]
                same_states = list(set(states).intersection(excluded_states))
                if len(same_states) > 0:
                    return True
        return False

    def set_states(self, state_list: List[str]):
        """
        Set the states of the container. Previous states will be removed.
        Raises a ParameterError if the state list contains exclusive states.

        :param state_list: List of states as strings
        :returns: Dictionary in the format {state: success}
        """
        if not state_list:
            state_list = []

        # Check for exclusive states
        exclusive_states = self._check_excluded_states(state_list)
        if exclusive_states:
            raise ParameterError(f"The state list {state_list} contains exclusive states!")

        # Remove old state entries
        TokenContainerStates.query.filter_by(container_id=self._db_container.id).delete()

        # Set new states
        state_types = self.get_state_types().keys()
        res = {}
        for state in state_list:
            if state not in state_types:
                # We do not raise an error here to allow following states to be set
                log.warning(f"State {state} not supported. Supported states are {state_types}.")
                res[state] = False
            else:
                TokenContainerStates(container_id=self._db_container.id, state=state).save()
                res[state] = True
        return res

    def add_states(self, state_list: List[str]):
        """
        Add states to the container. Previous states are only removed if a new state excludes them.
        Raises a ParameterError if the state list contains exclusive states.

        :param state_list: List of states as strings
        :returns: Dictionary in the format {state: success}
        """
        if not state_list or len(state_list) == 0:
            return {}

        # Check for exclusive states
        exclusive_states = self._check_excluded_states(state_list)
        if exclusive_states:
            raise ParameterError(f"The state list {state_list} contains exclusive states!")

        # Add new states
        res = {}
        state_types = self.get_state_types()
        for state in state_list:
            if state not in state_types.keys():
                # We do not raise an error here to allow following states to be set
                res[state] = False
                log.warning(f"State {state} not supported. Supported states are {state_types}.")
            else:
                # Remove old states that are excluded from the new state
                for excluded_state in state_types[state]:
                    TokenContainerStates.query.filter_by(container_id=self._db_container.id,
                                                         state=excluded_state).delete()
                    log.debug(
                        f"Removed state {excluded_state} from container {self.serial} "
                        f"because it is excluded by the new state {state}.")
                TokenContainerStates(container_id=self._db_container.id, state=state).save()
                res[state] = True
        return res

    @classmethod
    def get_state_types(cls):
        """
        Returns the state types that are supported by this container class and the states that are exclusive
        to each of these states.

        :return: Dictionary in the format: {state: [excluded_states]}
        """
        state_types_exclusions = {
            "active": ["disabled"],
            "disabled": ["active"],
            "lost": [],
            "damaged": []
        }
        return state_types_exclusions

    def set_container_info(self, info):
        """
        Set the containerinfo field in the DB. Old values will be deleted.

        :param info: dictionary in the format: {key: value}
        """
        self.delete_container_info()
        if info:
            self._db_container.set_info(info)

    def add_container_info(self, key, value):
        """
        Add a key and a value to the DB tokencontainerinfo

        :param key: key
        :param value: value
        """
        self._db_container.set_info({key: value})

    def get_container_info(self):
        """
        Return the tokencontainerinfo from the DB

        :return: list of tokencontainerinfo objects
        """
        return self._db_container.info_list

    def get_container_info_dict(self):
        """
        Return the tokencontainerinfo from the DB as dictionary

        :return: dictionary of tokencontainerinfo objects
        """
        container_info_list = self._db_container.info_list
        container_info_dict = {info.key: info.value for info in container_info_list}
        return container_info_dict

    def delete_container_info(self, key=None):
        """
        Delete the tokencontainerinfo from the DB

        :param key: key to delete, if None all keys are deleted
        """
        res = {}
        if key:
            container_infos = TokenContainerInfo.query.filter_by(container_id=self._db_container.id, key=key)
        else:
            container_infos = TokenContainerInfo.query.filter_by(container_id=self._db_container.id)
        for ci in container_infos:
            ci.delete()
            res[ci.key] = True
        if container_infos.count() == 0:
            log.debug(f"Container {self.serial} has no info with key {key} or no info at all.")
        return res

    def add_options(self, options):
        """
        Add the given options to the container.

        :param options: The options to add as dictionary
        """
        class_options = self.get_class_options()
        for key, value in options.items():
            option_values = class_options.get(key)
            if option_values is not None:
                if value in option_values:
                    self.add_container_info(key, value)
                else:
                    log.debug(f"Value {value} not supported for option key {key}.")
            else:
                log.debug(f"Option key {key} not found for container type {self.get_class_type()}.")

    @property
    def template(self):
        """
        Returns the template the container is based on.
        """
        return self._db_container.template

    @template.setter
    def template(self, template_name: str):
        """
        Set the template the container is based on.
        """
        db_template = TokenContainerTemplate.query.filter_by(name=template_name).first()
        if db_template:
            if db_template.container_type == self.type:
                self._db_container.template = db_template
                self._db_container.save()
            else:
                log.info(f"Template {template_name} is not compatible with container type {self.type}.")

    def init_registration(self, server_url, scope, registration_ttl, ssl_verify, params):
        """
        Initializes the registration: Generates a QR code containing all relevant data.

        :param server_url: URL of the server reachable for the client.
        :param scope: The URL the client contacts to finalize the registration e.g. "https://pi.net/container/register/finalize".
        :param registration_ttl: Time to live of the registration link in minutes.
        :param ssl_verify: Whether the client shall use ssl.
        :param params: Container specific parameters
        """
        raise privacyIDEAError("Registration is not implemented for this container type.")

    def finalize_registration(self, params):
        """
        Finalize the registration of a container.
        """
        raise privacyIDEAError("Registration is not implemented for this container type.")

    def terminate_registration(self):
        """
        Terminate the synchronisation of the container with privacyIDEA.
        """
        raise privacyIDEAError("Registration is not implemented for this container type.")

    def check_challenge_response(self, params: dict):
        """
        Checks if the response to a challenge is valid.
        """
        return False

    def create_challenge(self, scope, validity_time=2):
        """
        Create a challenge for the container.
        """
        return {}

    def validate_challenge(self, signature: bytes, public_key: EllipticCurvePublicKey, scope: str, transaction_id=None,
                           key: str = None, container: str = None, device_brand: str = None, device_model: str = None):
        """
        Verifies the response of a challenge:
            * Checks if challenge is valid (not expired)
            * Checks if the challenge is for the right scope
            * Verifies the signature
        Implicitly verifies the passphrase by adding it to the signature message. The passphrase needs to be defined in
        the challenge data. Otherwise, no passphrase is used.

        :param signature: Signature of the message
        :param public_key: Public key to verify the signature
        :param scope: endpoint to reach if the challenge is valid
        :param transaction_id: Transaction ID of the challenge, optional
        :param key: Key to be included in the signature, optional
        :param container: Container to be included in the signature, optional
        :param device_brand: Device brand to be included in the signature, optional
        :param device_model: Device model to be included in the signature, optional
        :return: True if the challenge response is valid, False otherwise
        """
        challenge_list = get_challenges(serial=self.serial, transaction_id=transaction_id)
        container_info = self.get_container_info_dict()
        hash_algorithm = container_info.get("hash_algorithm", "SHA256")
        verify_res = {"valid": False, "hash_algorithm": hash_algorithm}

        # Checks all challenges of the container, at least one must be valid
        for challenge in challenge_list:
            if challenge.is_valid():
                # Create message
                nonce = challenge.challenge
                times_stamp = challenge.timestamp.replace(tzinfo=timezone.utc).isoformat()
                extra_data = json.loads(challenge.data)
                passphrase = extra_data.get("passphrase_response")
                challenge_scope = extra_data.get("scope")
                # explicitly check the scope that the right challenge for the right endpoint is used
                if scope != challenge_scope:
                    log.debug(f"Scope {scope} does not match challenge scope {challenge_scope}.")
                    continue

                message = f"{nonce}|{times_stamp}|{self.serial}|{challenge_scope}"
                if device_brand:
                    message += f"|{device_brand}"
                if device_model:
                    message += f"|{device_model}"
                if passphrase:
                    passphrase = decryptPassword(passphrase)
                    message += f"|{passphrase}"
                if key:
                    message += f"|{key}"
                if container:
                    message += f"|{container}"

                # log to find reason for invalid signature
                log.debug(
                    f"Challenge data: nonce={nonce}, timestamp={times_stamp}, serial={self.serial}, scope={scope}")
                log.debug(f"Challenge data from client: device_brand={device_brand}, device_model={device_model}, "
                          f"key={key}, container={container} ")
                log.debug(f"Used hash algorithm: {hash_algorithm}")

                # Check signature
                try:
                    verify_res = verify_ecc(message.encode("utf-8"), signature, public_key, hash_algorithm)
                except InvalidSignature:
                    # It is not the right challenge
                    log.debug(f"Used hash algorithm to verify: {verify_res['hash_algorithm']}")
                    continue

                # Valid challenge: delete it
                challenge.delete()
                break
            else:
                # Delete expired challenge
                challenge.delete()

        return verify_res["valid"]

    def get_as_dict(self, include_tokens: bool = True, public_info: bool = True, additional_hide_info: list = None):
        """
        Returns a dictionary containing all properties, contained tokens, and owners

        :param include_tokens: If True, the tokens are included in the dictionary
        :param public_info: If True, only public information is included and sensitive information is omitted
        :param additional_hide_info: List of keys that shall be omitted from the dictionary
        :return: Dictionary with the container details

        Example response

        ::

            {
                "type": "smartphone",
                "serial": "SMPH00038DD3",
                "description": "My smartphone",
                "last_authentication": "2024-09-11T08:56:37.200336+00:00",
                "last_synchronization": "2024-09-11T08:56:37.200336+00:00",
                "states": ["active"],
                "info": {
                            "hash_algorithm": "SHA256",
                            "key_algorithm": "secp384r1"
                        },
                "realms": ["deflocal"],
                "users": [{"user_name": "testuser",
                           "user_realm": "deflocal",
                           "user_resolver": "internal",
                           "user_id": 1}],
                "tokens": ["TOTP000152D1", "HOTP00012345"]
            }
        """
        details = {"type": self.type,
                   "serial": self.serial,
                   "description": self.description,
                   "last_authentication": self.last_authentication.isoformat() if self.last_authentication else None,
                   "last_synchronization": self.last_synchronization.isoformat() if self.last_synchronization else None,
                   "states": self.get_states()}

        if public_info or additional_hide_info:
            black_key_list = []
            if public_info:
                black_key_list = ["public_key_container", "rollover_server_url", "rollover_challenge_ttl"]
            if additional_hide_info:
                black_key_list.extend(additional_hide_info)
            info = self.get_container_info()
            info_dict = {i.key: i.value for i in info if i.key not in black_key_list}
        else:
            info_dict = self.get_container_info_dict()
        details["info"] = info_dict

        template = self.template
        template_name = ""
        if template:
            template_name = template.name
        details["template"] = template_name

        realms = []
        for realm in self.realms:
            realms.append(realm.name)
        details["realms"] = realms

        users = []
        user_info = {}
        for user in self.get_users():
            user_info["user_name"] = user.login
            user_info["user_realm"] = user.realm
            user_info["user_resolver"] = user.resolver
            user_info["user_id"] = user.uid
            users.append(user_info)
        details["users"] = users

        if include_tokens:
            details["tokens"] = [token.get_serial() for token in self.get_tokens()]

        return details

    @classmethod
    def get_class_type(cls):
        """
        Returns the type of the container class.
        """
        return "generic"

    @classmethod
    def get_supported_token_types(cls):
        """
        Returns the token types that are supported by the container class.
        """
        supported_token_types = get_token_types()
        supported_token_types.sort()
        return supported_token_types

    @classmethod
    def get_class_prefix(cls):
        """
        Returns the container class specific prefix for the serial.
        """
        return "CONT"

    @classmethod
    def get_class_description(cls):
        """
        Returns a description of the container class.
        """
        return _("General purpose container that can hold any type and any number of token.")

    def encrypt_dict(self, container_dict: dict, params: dict):
        """
        Encrypts a dictionary with the public key of the container.
        It is not supported by all container classes. Classes not supporting the encryption raise a privacyIDEA error.
        """
        raise privacyIDEAError("Encryption is not implemented for this container type.")

    def synchronize_container_details(self, container_client: dict, initial_transfer_allowed: bool = False):
        """
        Compares the container from the client with the server and returns the differences.
        The container dictionary from the client contains information about the container itself and the tokens.
        For each token the type and serial shall be provided. If no serial is available, two otp values can be provided.
        The server than tries to find the serial for the otp values. If multiple serials are found, it will not be
        included in the returned dictionary, since the token can not be uniquely identified.
        The returned dictionary contains information about the container itself and the tokens that needs to be added
        or updated. For the tokens to be added the enrollUrl is provided. For the tokens to be updated at least the
        serial and the tokentype are provided.

        :param initial_transfer_allowed: If True, all tokens from the client are added to the container
        :param container_client: The container from the client as dictionary.
        An example container dictionary from the client:
            ::

                {
                    "container": {"type": "smartphone", "serial": "SMPH001"},
                    "tokens": [{"serial": "TOTP001", "type": "totp"},
                                {"otp": ["1234", "9876"], "type": "hotp"}]
                }

        :return: container dictionary
        An example of a returned container dictionary:
            ::

                {
                    "container": {"type": "smartphone", "serial": "SMPH001"},
                    "tokens": {"add": ["enroll_url1", "enroll_url2"],
                               "update": [{"serial": "TOTP001", "tokentype": "totp"},
                                          {"serial": "HOTP001", "otp": ["1234", "9876"],
                                           "tokentype": "hotp", "counter": 2}]}
                }
        """
        container_dict = {"container": {"type": self.type, "serial": self.serial}}
        server_token_serials = [token.get_serial() for token in self.get_tokens()]

        # Get serials for client tokens without serial
        client_tokens = container_client.get("tokens", [])
        serial_otp_map = {}
        for token in client_tokens:
            dict_keys = token.keys()
            # Get serial from otp if required
            if "serial" not in dict_keys and "otp" in dict_keys:
                token_type = token.get("tokentype")
                token_list = get_tokens(tokentype=token_type)
                serial_list = get_serial_by_otp_list(token_list, otp_list=token["otp"])
                if len(serial_list) == 1:
                    serial = serial_list[0]
                    token["serial"] = serial
                    serial_otp_map[serial] = token["otp"]
                elif len(serial_list) > 1:
                    log.debug(f"Multiple serials found for otp {token['otp']}. Ignoring this token.")
                # shall we ignore otp values where multiple serials are found?

        # map client and server tokens
        client_serials = [token["serial"] for token in client_tokens if "serial" in token.keys()]

        container_info = self.get_container_info_dict()
        registration_state = container_info.get("registration_state", "")
        if registration_state == "rollover":
            # rollover all tokens: generate new enroll info for all tokens
            missing_serials = server_token_serials
            same_serials = []
        else:
            missing_serials = list(set(server_token_serials).difference(set(client_serials)))
            same_serials = list(set(server_token_serials).intersection(set(client_serials)))

        # Initial synchronization after registration or rollover
        if initial_transfer_allowed and container_info.get("initial_synchronized") == "False":
            self.add_container_info("initial_synchronized", "True")
            server_missing_tokens = list(set(client_serials).difference(set(server_token_serials)))
            for serial in server_missing_tokens:
                # Try to add the missing token to the container on the server
                try:
                    token = get_tokens_from_serial_or_user(serial, None)[0]
                except ResourceNotFoundError:
                    log.info(f"Token {serial} from client does not exist on the server.")
                    continue

                try:
                    self.add_token(token)
                except ParameterError as e:
                    log.info(f"Client token {serial} could not be added to the container: {e}")
                    continue
                # add token to the same_serials list to update the token details
                same_serials.append(serial)

        # Get info for same serials: token details
        update_dict = []
        for serial in same_serials:
            token = get_tokens_from_serial_or_user(serial, None)[0]
            token_dict_all = token.get_as_dict()
            token_dict = {"serial": token_dict_all["serial"], "tokentype": token_dict_all["tokentype"]}
            # rename count to counter for the client
            if "count" in token_dict_all:
                token_dict["counter"] = token_dict_all["count"]

            # add otp values to allow the client identifying the token if he has no serial yet
            otp = serial_otp_map.get(serial)
            if otp:
                token_dict["otp"] = otp
            update_dict.append(token_dict)

        container_dict["tokens"] = {"add": missing_serials, "update": update_dict}

        return container_dict
