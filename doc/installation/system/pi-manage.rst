.. _pimanage:

The pi-manage Script
====================

.. index:: pi-manage

*pi-manage* is the script that is used during the installation process to
setup the database and do many other tasks.

.. note:: The interesting thing about pi-manage is, that it does not need
   the server to run as it acts directly on the database.
   Therefor you need read access to /etc/privacyidea/pi.cfg and the encryption
   key.

If you want to use a config file other than /etc/privacyidea/pi.cfg, you can
set an environment variable::

   PRIVACYIDEA_CONFIGFILE=/home/user/pi.cfg pi-manage

pi-manage always takes a command and sometimes a sub command::

   pi-manage <command> [<subcommand>] [<parameters>]

For a complete list of commands and sub commands use the *-h* parameter.

You can do the following tasks.

Encryption Key
--------------

You can create an encryption key and encrypt the encryption key.

Create encryption key::

   pi-manage setup create_enckey [--enckey_b64=BASE64_ENCODED_ENCKEY]

.. note:: The filename of the encryption
   key is read from the configuration. The key will not be created, if it
   already exists.
   Optionally, enckey can be passed via `--enckey_b64` argument, but it is not recommended.
   `--enckey_b64` must be a string with 96 bytes, encoded in base 64 in order to avoid ambiguous chars.

The encryption key is a plain file on your hard drive. You need to take care,
to set the correct access rights.

You can also encrypt the encryption key with a passphrase. To do this do::

   pi-manage setup encrypt_enckey /etc/privacyidea/enckey

and pipe the encrypted *enckey* to a new file.

Read more about the database encryption and the *enckey* in :ref:`securitymodule`.

Backup and Restore
------------------

.. index:: Backup, Restore

You can create a backup which will be save to */var/lib/privacyidea/backup/*.

The backup will contain the database dump and the complete directory
*/etc/privacyidea*. You may choose if you want to add the encryption key to
the backup or not.

.. warning:: If the backup includes the database dump and the encryption key
   all seeds of the OTP tokens can be read from the backup.

As the backup contains the etc directory and the database you only need this
tar archive backup to perform a complete restore.


Rotate Audit Log
----------------

Audit logs are written to the database. You can use pi-manage to perform a
log rotation::

   pi-manage audit rotate

You can specify a highwatermark and a lowwatermark, age or a config file. Read more
about it at :ref:`cleaning up audit entries <audit_rotate>`.

.. _pimanage_challenge:

Clean up challenges
-------------------

The challenges of challenge-response tokens are stored in a database table.
Each challenge has a validity time. Challenges which haven't been answered,
persist in the database and must be cleaned up manually. To clean up all
expired challenges use::

   pi-manage config challenge cleanup

To clean up challenges older than a certain age (in minutes), use the parameter
``--age``::

   pi-manage config challenge cleanup --age 10

This will clean up challenges that were created more than 10 minutes ago.

Use ``--chunksize`` to avoid deadlocks when cleaning up a large challenge table.
To get only the number of challenges which would be deleted, use ``--dryrun``.

API Keys
--------

You can use ``pi-manage`` to create API keys. API keys can be used to

1. secure the access to the ``/validate/check`` API or
2. to access administrative tasks via the REST API.

You can create API keys for ``/validate/check`` using the command::

   pi-manage api createtoken -r validate

If you want to secure the access to ``/validate/check`` you also need to
define a policy in scope ``authorizaion``. See :ref:`policy_api_key`.

If you wan to use the API key to automate administrative REST API calls, you
can use the command::

   pi-manage api createtoken -r admin

This command also generates an admin account name. But it does not create
this admin account. You need to do so using ``pi-manage admin``.
You can now use this API key to enroll tokens as administrator.

.. note:: These API keys are not persistent. They are not stored in the
   privacyIDEA server. The API key is connected to the username, that is also
   generated. This means you have to create an administrative account with
   this very username to use this API key for this admin user.
   You also should set policies for this admin user, so that this API key has
   only restricted rights!

.. note:: The API key is valid for 365 days.

Policies
--------

You can use ``pi-manage config policy`` to enable, disable, create and delete policies.
Using the sub commands ``config export -t policy`` and ``config import -t policy`` you can also export a
backup of your policies and import this policy set later.

This could also be used to transfer the policies from one privacyIDEA
instance to another.
