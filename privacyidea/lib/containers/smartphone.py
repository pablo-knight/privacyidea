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
import base64
import logging
from datetime import timezone
from urllib.parse import quote

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from flask import json

from privacyidea.api.lib.utils import getParam
from privacyidea.lib import _
from privacyidea.lib.apps import _construct_extra_parameters
from privacyidea.lib.challenge import get_challenges
from privacyidea.lib.containerclass import TokenContainerClass
from privacyidea.lib.crypto import (geturandom, encryptPassword, b64url_str_key_pair_to_ecc_obj,
                                    ecc_key_pair_to_b64url_str, generate_keypair_ecc, encrypt_ecc)
from privacyidea.lib.error import (ContainerInvalidChallenge, ContainerNotRegistered, ResourceNotFoundError,
                                   ParameterError)
from privacyidea.lib.token import get_tokens_from_serial_or_user, get_tokens, get_serial_by_otp_list
from privacyidea.lib.utils import create_img
from privacyidea.models import Challenge

log = logging.getLogger(__name__)


def create_container_registration_url(nonce, time_stamp, server_url, container_serial, key_algorithm,
                                      hash_algorithm, extra_data={}, passphrase="", issuer="privacyIDEA", ttl=10,
                                      ssl_verify=True):
    """
    Create a URL for binding a container to a physical container.

    :param nonce: Nonce (some random bytes).
    :param time_stamp: Timestamp of the registration in iso format.
    :param server_url: URL of the server reachable for the client.
    :param container_serial: Serial of the container.
    :param key_algorithm: Algorithm to use to generate the ECC key pair, e.g. 'secp384r1'.
    :param hash_algorithm: Hash algorithm to be used in the signing algorithm, e.g. 'SHA256'.
    :param extra_data: Extra data to be included in the URL.
    :param passphrase: Passphrase Prompt to be displayed to the user in the app.
    :param issuer: Issuer of the registration, e.g. 'privacyIDEA'.
    :param ttl: Time to live of the URL in seconds.
    :param ssl_verify: Whether the smartphone shall verify the SSL certificate of the server.
    :return: URL for binding a container to a physical container.
    """
    url_nonce = quote(nonce.encode("utf-8"))
    url_time_stamp = quote(time_stamp.encode("utf-8"))
    url_label = quote(container_serial.encode("utf-8"))
    url_issuer = quote(issuer.encode("utf-8"))
    url_extra_data = _construct_extra_parameters(extra_data)
    url_passphrase = quote(passphrase.encode("utf-8"))
    url_key_algorithm = quote(key_algorithm.encode("utf-8"))
    url_hash_algorithm = quote(hash_algorithm.encode("utf-8"))
    url_ssl_verify = quote(ssl_verify.encode("utf-8"))

    url = (f"pia://container/{url_label}?issuer={url_issuer}&ttl={ttl}&nonce={url_nonce}&time={url_time_stamp}"
           f"&url={server_url}&serial={container_serial}&key_algorithm={url_key_algorithm}"
           f"&hash_algorithm={url_hash_algorithm}&ssl_verify={url_ssl_verify}&passphrase={url_passphrase}{url_extra_data}")
    return url


class SmartphoneOptions:
    """
    Options for the smartphone container.
    """
    KEY_ALGORITHM = "key_algorithm"
    HASH_ALGORITHM = "hash_algorithm"
    ENCRYPT_KEY_ALGORITHM = "encrypt_key_algorithm"
    ENCRYPT_ALGORITHM = "encrypt_algorithm"
    ENCRYPT_MODE = "encrypt_mode"


class SmartphoneContainer(TokenContainerClass):
    # The first value in the list is the default value
    options = {SmartphoneOptions.KEY_ALGORITHM: ["secp384r1"],
               SmartphoneOptions.HASH_ALGORITHM: ["SHA256"],
               SmartphoneOptions.ENCRYPT_KEY_ALGORITHM: ["x25519"],
               SmartphoneOptions.ENCRYPT_ALGORITHM: ["AES"],
               SmartphoneOptions.ENCRYPT_MODE: ["GCM"]}

    def __init__(self, db_container):
        super().__init__(db_container)

    @classmethod
    def get_class_type(cls):
        """
        Returns the type of the container class.
        """
        return "smartphone"

    @classmethod
    def get_supported_token_types(cls):
        """
        Returns the token types that are supported by the container class.
        """
        supported_token_types = ["hotp", "totp", "push", "daypassword", "sms"]
        supported_token_types.sort()
        return supported_token_types

    @classmethod
    def get_class_prefix(cls):
        """
        Returns the container class specific prefix for the serial.
        """
        return "SMPH"

    @classmethod
    def get_class_description(cls):
        """
        Returns a description of the container class.
        """
        return _("A smartphone that uses an authenticator app.")

    def init_registration(self, server_url, scope, registration_ttl, ssl_verify, params={}):
        """
        Initializes the registration: Generates a QR code containing all relevant data.

        :param server_url: URL of the server reachable for the client.
        :param scope: The URL the client contacts to finalize the registration e.g. "https://pi.net/container/register/finalize".
        :param registration_ttl: Time to live of the registration link in minutes.
        :param ssl_verify: Whether the client shall use ssl.
        :param params: Container specific parameters like
        An example params dictionary:
            ::

                {
                    "passphrase_ad": <bool, whether the AD password shall be used>, (optional)
                    "passphrase_prompt": <str, the prompt for the passphrase displayed in the app>, (optional)
                    "passphrase_response": <str, passphrase>, (optional)
                    "extra_data": <dict, any additional data>, (optional)
                }

        :return: A dictionary with the registration data

        An example of a returned dictionary:
            ::

                {
                    "container_url": {
                        "description": "URL for privacyIDEA Container Registration",
                        "value": <url>,
                        "img": <qr code of url>
                    },
                    "nonce": "ajhbdsuiuojno49877n4no3u09on38r98n",
                    "time_stamp": "2020-08-25T14:00:00.000000+00:00",
                    "key_algorithm": "secp384r1",
                    "hash_algorithm": "SHA256",
                    "ssl_verify": <bool>,
                    "ttl": <int>,
                    "passphrase": <Passphrase prompt displayed to the user in the app> (optional)
                }
        """
        # get params
        extra_data = getParam(params, 'extra_data', optional=True) or {}
        passphrase_ad = getParam(params, 'passphrase_ad', optional=True) or False
        passphrase_prompt = getParam(params, 'passphrase_prompt', optional=True) or ""
        passphrase_response = getParam(params, 'passphrase_response', optional=True) or ""
        if passphrase_ad:
            if not passphrase_prompt:
                passphrase_prompt = "Please enter your AD passphrase."
        if passphrase_response:
            passphrase_response = encryptPassword(passphrase_response)
        challenge_params = {"scope": scope, "passphrase_prompt": passphrase_prompt,
                            "passphrase_response": passphrase_response,
                            "passphrase_ad": passphrase_ad}

        # Delete all other challenges for this container
        challenge_list = get_challenges(serial=self.serial)
        for challenge in challenge_list:
            challenge.delete()

        # Create challenge
        res = self.create_challenge(scope=scope, validity_time=registration_ttl, data=challenge_params)
        time_stamp_iso = res["time_stamp"]
        nonce = res["nonce"]

        # set all options and get algorithms
        class_options = self.get_class_options()
        options = {}
        for key in list(class_options.keys()):
            value = self.set_default_option(key)
            if value is not None:
                options[key] = value
        key_algorithm = options[SmartphoneOptions.KEY_ALGORITHM]
        hash_algorithm = options[SmartphoneOptions.HASH_ALGORITHM]

        # Generate URL
        qr_url = create_container_registration_url(nonce=nonce,
                                                   time_stamp=time_stamp_iso,
                                                   server_url=server_url,
                                                   container_serial=self.serial,
                                                   key_algorithm=key_algorithm,
                                                   hash_algorithm=hash_algorithm,
                                                   passphrase=passphrase_prompt,
                                                   ttl=registration_ttl,
                                                   ssl_verify=ssl_verify,
                                                   extra_data=extra_data)
        # Generate QR code
        qr_img = create_img(qr_url)

        # Set container info
        self.add_container_info("registration_state", "client_wait")

        # Response
        response_detail = {"container_url": {"description": _("URL for privacyIDEA Container Registration"),
                                             "value": qr_url,
                                             "img": qr_img},
                           "nonce": nonce,
                           "time_stamp": time_stamp_iso,
                           "key_algorithm": key_algorithm,
                           "hash_algorithm": hash_algorithm,
                           "ssl_verify": ssl_verify,
                           "ttl": registration_ttl,
                           "passphrase_prompt": passphrase_prompt,
                           "server_url": server_url}

        return response_detail

    def finalize_registration(self, params):
        """
        Finalize the registration of a pi container on a physical container.
        Validates whether the smartphone is authorized to register. If successful, the server generates a key pair.
        Raises a privacyIDEAError on any failure to not disclose information.

        :param params: The parameters from the smartphone for the registration as dictionary like:
        An example params dictionary:
            ::

                {
                    "container_serial": <serial of the container>,
                    "signature": <sign(message)>,
                    "message": <nonce|timestamp|registration_url|serial[|passphrase]>,
                    "public_key": <public key of the smartphone base 64 url safe encoded>,
                    "device_brand": <Brand of the smartphone> (optional),
                    "device_model": <Model of the smartphone> (optional),
                    "passphrase": <passphrase> (optional)
                }

        :return: The public key of the server in a dictionary like {"public_key": <pub key base 64 url encoded>}.
        """
        # Get params
        signature = base64.urlsafe_b64decode(getParam(params, "signature", optional=False))
        pub_key_container_str = getParam(params, "public_client_key", optional=False)
        pub_key_container, _ = b64url_str_key_pair_to_ecc_obj(public_key_str=pub_key_container_str)
        scope = getParam(params, "scope", optional=False)
        device_brand = getParam(params, "device_brand", optional=True)
        device_model = getParam(params, "device_model", optional=True)
        device = ""
        if device_brand:
            device += device_brand
        if device_model:
            device += f" {device_model}"

        # Verifies challenge
        valid = self.validate_challenge(signature, pub_key_container, scope=scope, device_brand=device_brand,
                                        device_model=device_model)
        if not valid:
            raise ContainerInvalidChallenge('Could not verify signature!')

        # Generate private + public key for the server
        container_info = self.get_container_info_dict()
        key_algorithm = container_info.get("key_algorithm", "secp384r1")
        public_key_server, private_key_server = generate_keypair_ecc(key_algorithm)
        public_key_server_str, private_key_server_str = ecc_key_pair_to_b64url_str(public_key_server,
                                                                                   private_key_server)

        # Update container info
        pub_key_container_str = getParam(params, "public_client_key", optional=False)
        self.add_container_info("public_key_container", pub_key_container_str)
        self.add_container_info("public_key_server", public_key_server_str)
        self.add_container_info("private_key_server", encryptPassword(private_key_server_str))
        if device != "":
            self.add_container_info("device", device)
        else:
            # this might be a rollover, delete old device information
            self.delete_container_info("device")

        # The rollover is completed with the first synchronization
        registration_state = container_info.get("registration_state", "")
        if registration_state != "rollover":
            self.add_container_info("registration_state", "registered")

        # check right for initial token transfer
        if params.get("client_policies", {}).get("container_initial_token_transfer"):
            self.add_container_info("initial_synchronized", False)

        res = {"public_server_key": public_key_server_str}

        return res

    def terminate_registration(self):
        """
        Terminate the synchronisation of the container with privacyIDEA.
        The associated information is deleted from the container info and all challenges for this container are deleted
        as well.
        """
        # Delete registration / synchronization info
        self.delete_container_info("public_key_container")
        self.delete_container_info("public_key_server")
        self.delete_container_info("private_key_server")
        self.delete_container_info("device")
        self.delete_container_info("server_url")
        self.delete_container_info("registration_state")
        self.delete_container_info("challenge_ttl")
        self.delete_container_info("initial_synchronized")

    def create_challenge(self, scope, validity_time=2, data={}):
        """
        Create a challenge for the container.

        :param scope: The scope (endpoint) of the challenge, e.g. "container/SMPH001/sync"
        :param validity_time: The validity time of the challenge in minutes.
        :param data: Additional data for the challenge.
        :return: A dictionary with the challenge data

        An example of a returned challenge dictionary:
            ::

                {
                    "nonce": <nonce>,
                    "time_stamp": <timestamp iso format>,
                    "enc_key_algorithm": <encryption key algorithm>
                }
        """
        # Create challenge
        nonce = geturandom(20, hex=True)
        data["scope"] = scope
        data["type"] = "container"
        data_str = json.dumps(data)
        if validity_time:
            validity_time *= 60
        db_challenge = Challenge(serial=self.serial, challenge=nonce, data=data_str, validitytime=validity_time)
        db_challenge.save()
        timestamp = db_challenge.timestamp.replace(tzinfo=timezone.utc)
        time_stamp_iso = timestamp.isoformat()

        # Get encryption info (optional)
        container_info = self.get_container_info_dict()
        enc_key_algorithm = container_info.get(SmartphoneOptions.ENCRYPT_KEY_ALGORITHM)

        res = {"nonce": nonce,
               "time_stamp": time_stamp_iso,
               "enc_key_algorithm": enc_key_algorithm}
        return res

    def check_challenge_response(self, params):
        """
        Checks if the response to a challenge is valid.

        :param params: Dictionary with the parameters for the challenge.

        An example params dictionary:
            ::

                {
                    "signature": <sign(nonce|timestamp|serial|scope|pub_key|container_dict)>,
                    "public_client_key_encry": <public key of the client for encryption base 64 url safe encoded>,
                    "container_dict_client": {"serial": "SMPH0001", "type": "smartphone", ...}
                }

        :return: True if a valid challenge exists, raises a privacyIDEAError otherwise.
        """
        # Get params
        signature = base64.urlsafe_b64decode(getParam(params, "signature", optional=False))
        pub_key_encr_container_str = getParam(params, "public_enc_key_client", optional=True)
        container_client_str = getParam(params, "container_dict_client", optional=True)
        scope = getParam(params, "scope", optional=False)
        device_brand = getParam(params, "device_brand", optional=True)
        device_model = getParam(params, "device_model", optional=True)

        try:
            pub_key_sig_container_str = self.get_container_info_dict()["public_key_container"]
        except KeyError:
            raise ContainerNotRegistered("The container is not registered or was unregistered!")
        pub_key_sig_container, _ = b64url_str_key_pair_to_ecc_obj(public_key_str=pub_key_sig_container_str)

        # Validate challenge
        valid_challenge = self.validate_challenge(signature, pub_key_sig_container, scope=scope,
                                                  key=pub_key_encr_container_str,
                                                  container=container_client_str,
                                                  device_brand=device_brand,
                                                  device_model=device_model)
        if not valid_challenge:
            raise ContainerInvalidChallenge('Could not verify signature!')

        return valid_challenge

    def encrypt_dict(self, container_dict: dict, params: dict):
        """
        Encrypt a container dictionary.

        :param container_dict: The container dictionary to be encrypted.
        :param params: Dictionary with the parameters for the encryption from the client.
        :return: Dictionary with the encrypted container dictionary and further encryption parameters

        An example of a returned dictionary:
            ::

                {
                    "public_server_key_encry": <public key of the server for encryption base 64 url safe encoded>,
                    "encryption_algorithm": "AES",
                    "encryption_params": {"mode": "GCM", "init_vector": "init_vector", "tag": "tag"},
                    "container_dict_server": <encrypted container dict from server>
                }
        """
        pub_key_encr_container_str = getParam(params, "public_enc_key_client", optional=False)
        pub_key_encr_container_bytes = base64.urlsafe_b64decode(pub_key_encr_container_str)
        pub_key_encr_container = X25519PublicKey.from_public_bytes(pub_key_encr_container_bytes)

        # Generate encryption key pair for the server
        container_info = self.get_container_info_dict()
        enc_key_algorithm = container_info.get(SmartphoneOptions.ENCRYPT_KEY_ALGORITHM)
        public_key_encr_server, private_key_encr_server = generate_keypair_ecc(enc_key_algorithm)
        public_key_encr_server_str = base64.urlsafe_b64encode(public_key_encr_server.public_bytes_raw()).decode('utf-8')

        # Get encryption algorithm and mode
        container_info = self.get_container_info_dict()
        encrypt_algorithm = container_info.get(SmartphoneOptions.ENCRYPT_ALGORITHM)
        encrypt_mode = container_info.get(SmartphoneOptions.ENCRYPT_MODE)

        # encrypt container dict
        session_key = private_key_encr_server.exchange(pub_key_encr_container)
        container_dict_bytes = json.dumps(container_dict).encode('utf-8')
        container_dict_encrypted, encryption_params = encrypt_ecc(container_dict_bytes, session_key, encrypt_algorithm,
                                                                  encrypt_mode)

        res = {"encryption_algorithm": encrypt_algorithm,
               "encryption_params": encryption_params,
               "container_dict_server": container_dict_encrypted,
               "public_server_key": public_key_encr_server_str}
        return res

    def synchronize_container_details(self, container_client: dict, initial_transfer_allowed: bool = False):
        """
        Compares the container from the client with the server and returns the differences.
        The container dictionary from the client contains information about the container itself and the tokens.
        For each token the type and serial shall be provided. If no serial is available, two otp values can be provided.
        The server than tries to find the serial for the otp values. If multiple serials are found, it will not be
        included in the returned dictionary, since the token can not be uniquely identified.
        The returned dictionary contains information about the container itself and the tokens that needs to be added
        or updated. For the tokens to be added the enrollUrl is provided. For the tokens to be updated the serial and
        further information is provided.

        :param initial_transfer_allowed: If True, all tokens from the client are added to the container
        :param container_client: The container from the client as dictionary.
        An example container dictionary from the client:
            ::

                {
                    "container": {"states": ["active"]},
                    "tokens": [{"serial": "TOTP001", "type": "totp", "active: True},
                                {"otp": ["1234", "9876"], "type": "hotp"}]
                }

        :return: container dictionary like
        An example of a returned container dictionary:
            ::

                {
                    "container": {"states": ["active"]},
                    "tokens": {"add": ["enroll_url1", "enroll_url2"],
                               "update": [{"serial": "TOTP001", "active": True},
                                          {"serial": "HOTP001", "active": False, "otp": ["1234", "9876"],
                                           "type": "hotp"}]}
                }
        """
        container_info = self.get_container_info_dict()
        container_dict = {"container": self.get_as_dict(include_tokens=False, public_info=True)}
        server_token_serials = [token.get_serial() for token in self.get_tokens()]

        # Get serials for client tokens without serial
        client_tokens = container_client.get("tokens", [])
        serial_otp_map = {}
        for token in client_tokens:
            dict_keys = token.keys()
            # Get serial from otp if required
            if "serial" not in dict_keys and "otp" in dict_keys:
                token_type = token.get("type")
                token_list = get_tokens(tokentype=token_type)
                serial_list = get_serial_by_otp_list(token_list, otp_list=token["otp"])
                if len(serial_list) == 1:
                    serial = serial_list[0]
                    token["serial"] = serial
                    serial_otp_map[serial] = token["otp"]
                # shall we ignore otp values where multiple serials are found?

        # map client and server tokens
        client_serials = [token["serial"] for token in client_tokens if "serial" in token.keys()]

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
        black_list_token_info = ["private_key_server", "private_key_server.type"]
        for serial in same_serials:
            token = get_tokens_from_serial_or_user(serial, None)[0]
            token_dict = token.get_as_dict()
            # rename count to counter for the client
            if "count" in token_dict:
                token_dict["counter"] = token_dict["count"]
                del token_dict["count"]

            # remove sensible token infos
            for key in black_list_token_info:
                if key in token_dict["info"]:
                    del token_dict["info"][key]

            # add otp values to allow the client identifying the token if he has no serial yet
            otp = serial_otp_map.get(serial)
            if otp:
                token_dict["otp"] = otp
            update_dict.append(token_dict)

        container_dict["tokens"] = {"add": missing_serials, "update": update_dict}

        return container_dict
