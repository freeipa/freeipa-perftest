#!/usr/bin/python3

#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import click
import os

from ipalib import api
from ipapython.ipautil import run


@click.command("cli", context_settings={"show_default": True})
@click.option("--users-per-host", default=10,
              help="Number of users for each host.",
              type=int)
@click.option("--hosts", default=500, help="Number of hosts.",
              type=int)
@click.option("--host-prefix", default="client", help="hostname prefix")
@click.option("--dm-password", default=None, required=True,
              help="Directory manager password.")
@click.option("--debug", default=False, help="Debug logging", is_flag=True)
def main(users_per_host, hosts, host_prefix, dm_password, debug):
    api.bootstrap(in_server=True, context='server', in_tree=False,
                  debug=debug)
    api.finalize()

    keytab = '/tmp/kt'
    for i in range(0, hosts):
        hostname = '{}{:03d}.{}'.format(host_prefix, i, api.env.domain)
        for i in range(0, users_per_host):
            uid = 'user{}{}'.format(i, hostname)
            principal = '{}@{}'.format(uid, api.env.realm)
            args = [
                    '/usr/sbin/ipa-getkeytab',
                    '-k', keytab,
                    '--password',
                    '-p', principal,
                    '-D', 'cn=directory manager',
                    '--bindpw', dm_password,
            ]
            run(args, stdin='password\npassword')
            print(principal)
            os.remove(keytab)


if __name__ == '__main__':
    main()
