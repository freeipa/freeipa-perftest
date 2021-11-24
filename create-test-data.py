#!/usr/bin/python3

#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import click
import math
import sys
from datetime import datetime, timedelta
from ipalib import api


class IPAData(object):
    def __init__(
            self, domain, basedn, realm,
            users=50000,
            hosts=40000,
            host_prefix="client",
            outfile=None,
    ):

        # TBD: compute everything else based on users and groups
        """
        groups=1000,
        groups_per_user=20,
        nested_groups_max_level=2,
        nested_groups_per_user=10,
        hostgroups=1000,
        hostgroups_per_host=10,
        nested_hostgroups_max_level=2,
        nested_hostgroups_per_host=5,
        direct_sudorules=20,  # users, hosts
        indirect_sudorules=80,  # groups, hostgroups
        sudorules_per_user=5,
        sudorules_per_group=2,
        sudorules_per_host=5,
        sudorules_per_hostgroup=5,
        direct_hbac=20,  # users, hosts
        indirect_hbac=80,  # groups, hostgroups
        hbac_per_user=5,
        hbac_per_group=2,
        hbac_per_host=5,
        hbac_per_hostgroup=5
        """
        self.host_prefix = host_prefix
        groups = 0
        groups_per_user = 0
        nested_groups_max_level = 0
        nested_groups_per_user = 0
        hostgroups = 0
        hostgroups_per_host = 0
        nested_hostgroups_max_level = 0
        nested_hostgroups_per_host = 0
        direct_sudorules = 0  # users, hosts
        indirect_sudorules = 0  # groups, hostgroups
        sudorules_per_user = 0
        sudorules_per_group = 0
        sudorules_per_host = 0
        sudorules_per_hostgroup = 0
        direct_hbac = 0  # users, hosts
        indirect_hbac = 0  # groups, hostgroups
        hbac_per_user = 0
        hbac_per_group = 0
        hbac_per_host = 0
        hbac_per_hostgroup = 0

        self.domain = domain
        self.basedn = basedn
        self.realm = realm

        if outfile:
            self.stream = open(outfile, "w")
        else:
            self.stream = sys.stdout

        self.users = users
        self.groups = groups

        self.groups_per_user = groups_per_user
        self.nested_groups_max_level = nested_groups_max_level
        self.nested_groups_per_user = nested_groups_per_user

        self.hosts = hosts
        self.hostgroups = hostgroups

        self.hostgroups_per_host = hostgroups_per_host
        self.nested_hostgroups_max_level = nested_hostgroups_max_level
        self.nested_hostgroups_per_host = nested_hostgroups_per_host

        self.direct_sudorules = direct_sudorules
        self.indirect_sudorules = indirect_sudorules
        self.sudorules_per_user = sudorules_per_user
        self.sudorules_per_group = sudorules_per_group
        self.sudorules_per_host = sudorules_per_host
        self.sudorules_per_hostgroup = sudorules_per_hostgroup
        self.direct_hbac = direct_hbac
        self.indirect_hbac = indirect_hbac
        self.hbac_per_user = hbac_per_user
        self.hbac_per_group = hbac_per_group
        self.hbac_per_host = hbac_per_host
        self.hbac_per_hostgroup = hbac_per_hostgroup

        _sshpubkey = (
            'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDGAX3xAeLeaJggwTqMjxNwa'
            '6XHBUAikXPGMzEpVrlLDCZtv00djsFTBi38PkgxBJVkgRWMrcBsr/35lq7P6w'
            '8KGIwA8GI48Z0qBS2NBMJ2u9WQ2hjLN6GdMlo77O0uJY3251p12pCVIS/bHRS'
            'q8kHO2No8g7KA9fGGcagPfQH+ee3t7HUkpbQkFTmbPPN++r3V8oVUk5LxbryB'
            '3UIIVzNmcSIn3JrXynlvui4MixvrtX6zx+O/bBo68o8/eZD26QrahVbA09fiv'
            'rn/4h3TM019Eu/c2jOdckfU3cHUV/3Tno5d6JicibyaoDDK7S/yjdn5jhaz8M'
            'SEayQvFkZkiF0L public key test'
        )

        # encrypted value of 'password'
        _password = (
            '{PBKDF2_SHA256}AAAIAG+ooTntmgayOuMZRJuCMFVykCVWcVF3tw8YTlvFp9'
            'KF9UnFYhgpz8fC03o4Jv5KD4rQ4GsdXHIRlg/doyd1xOVFDYUZYAPHjnSpm9X'
            'nzIcaS4ZCV/JeLqueyeZQWKOlCH+k9BCmO2HZC7AKXWGMG5bJ8GLALceyf0xi'
            'oP447wehg8caWYY7f2VYBz6k233DUkgV5NqswzuEwtLdDDFjpro0Ac15ok6fS'
            '0vqjDfiMs0ai5FCbivEKw4j6ZyuXHCpck6gcH8lh33rs779ZaLAgtIeeW+xde'
            'a3BDCQXhuHwCqIxxifLn2gQy/lLxlikXb82gk2ClADhwoG5RIdJ3ABrPDB100'
            'yw6QJ7NF14vV7DDzqxqylocWD/l1xw8HIYdkCpRG8PyfLz8TOR+Mgq0uB/mdd'
            'rSkU6Hsmg9MkGpST69av'
        )

        utcnow = datetime.utcnow()
        twoyears = timedelta(days=365*2)
        expiration = (utcnow + twoyears).strftime("%Y%m%d%H%M%SZ")

        self.user_defaults = {
            'objectClass': [
                'ipaobject',
                'person',
                'top',
                'ipasshuser',
                'inetorgperson',
                'organizationalperson',
                'krbticketpolicyaux',
                'krbprincipalaux',
                'inetuser',
                'posixaccount',
                'ipaSshGroupOfPubKeys',
                'mepOriginEntry'],
            'ipaUniqueID': ['autogenerate'],
            'loginShell': ['/bin/zsh'],
            'uidNumber': ['-1'],
            'gidNumber': ['-1'],
            'ipaSshPubKey': [_sshpubkey],
            'krbExtraData': [
                'this-will-not-work-this-is-a-placeholder-for-IPA-framework-'
                'dont-try-to-kinit-with-this-because-it-will-blow-up'
            ],
            'krbLastPwdChange': [utcnow.strftime("%Y%m%d%H%M%SZ")],
            'krbPasswordExpiration': [expiration],
            'userpassword': [_password],
        }

        self.group_defaults = {
            'objectClass': [
                'ipaobject',
                'top',
                'ipausergroup',
                'posixgroup',
                'groupofnames',
                'nestedgroup', ],
            'ipaUniqueID': ['autogenerate'],
            'gidNumber': [-1],
        }

        self.host_defaults = {
            'objectClass': [
                'ipaobject',
                'ieee802device',
                'nshost',
                'ipaservice',
                'pkiuser',
                'ipahost',
                'krbprincipal',
                'krbprincipalaux',
                'ipasshhost',
                'top',
                'ipaSshGroupOfPubKeys',
            ],
            'ipaUniqueID': ['autogenerate'],
            'ipaSshPubKey': [_sshpubkey],
            'krbExtraData': [
                'this-will-not-work-this-is-a-placeholder-for-IPA-framework-'
                'dont-try-to-kinit-with-this-because-it-will-blow-up'
            ],
            'krbLastPwdChange': ['20160408125354Z'],
            'krbPasswordExpiration': ['20160408125354Z'],
        }

        self.hostgroup_defaults = {
            'objectClass': [
                'ipahostgroup',
                'ipaobject',
                'nestedGroup',
                'groupOfNames',
                'top',
                'mepOriginEntry',
            ],
            'ipaUniqueID': ['autogenerate'],
        }

        self.sudo_defaults = {
            'objectClass': [
                'ipasudorule',
                'ipaassociation',
            ],
            'ipaEnabledFlag': ['TRUE'],
            'ipaUniqueID': ['autogenerate'],
        }

        self.hbac_defaults = {
            'objectClass': [
                'ipahbacrule',
                'ipaassociation',
            ],
            'ipaEnabledFlag': ['TRUE'],
            'ipaUniqueID': ['autogenerate'],
            'accessRuleType': ['allow'],
        }

    def put_entry(self, entry):
        """
        Abstract method, implementation depends on if we want just print LDIF,
        or update LDAP directly
        """
        raise NotImplementedError()

    def gen_user(self, uid):
        user = dict(self.user_defaults)
        user['dn'] = 'uid={uid},cn=users,cn=accounts,{suffix}'.format(
            uid=uid,
            suffix=self.basedn,
        )
        user['uid'] = [uid]
        user['displayName'] = ['{} {}'.format(uid, uid)]
        user['initials'] = ['{}{}'.format(uid[1], uid[-1])]
        user['gecos'] = user['displayName']
        user['sn'] = [uid]
        user['homeDirectory'] = ['/other-home/{}'.format(uid)]
        user['mail'] = ['{uid}@{domain}'.format(
            uid=uid, domain=self.domain)]
        user['krbPrincipalName'] = ['{uid}@{realm}'.format(
            uid=uid, realm=self.realm)]
        user['krbCanonicalName'] = ['{uid}@{realm}'.format(
            uid=uid, realm=self.realm)]
        user['givenName'] = [uid]
        user['cn'] = ['{} {}'.format(uid, uid)]

        return user

    def username_generator(self, start, stop, step=1):
        for i in range(start, stop, step):
            yield 'user%d' % i

    def gen_group(self, name, members=(), group_members=()):
        group = dict(self.group_defaults)
        group['dn'] = 'cn={name},cn=groups,cn=accounts,{suffix}'.format(
            name=name,
            suffix=self.basedn,
        )
        group['cn'] = [name]
        group['member'] = ['uid={uid},cn=users,cn=accounts,{suffix}'.format(
            uid=uid,
            suffix=self.basedn,
        ) for uid in members]
        group['member'].extend(
            ['cn={name},cn=groups,cn=accounts,{suffix}'.format(
                name=name,
                suffix=self.basedn,
            ) for name in group_members])
        return group

    def groupname_generator(self, start, stop, step=1):
        for i in range(start, stop, step):
            yield 'group%s' % i

    def gen_host(self, hostname):
        host = dict(self.host_defaults)
        host['dn'] = 'fqdn={hostname},cn=computers,cn=accounts,{suffix}'.format(
            hostname=hostname,
            suffix=self.basedn
        )
        host['fqdn'] = [hostname]
        host['cn'] = [hostname]
        host['managedBy'] = [host['dn']]
        host['krbPrincipalName'] = ['host/{hostname}@{realm}'.format(
            hostname=hostname,
            realm=self.realm
        )]
        host['serverHostName'] = [hostname.split('.')[1]]
        return host

    def hostname_generator(self, start, stop, step=1):
        for i in range(start, stop, step):
            yield 'host{}.{}'.format(
                i, self.domain
            )

    def gen_hostgroup(self, name, members=(), group_members=()):
        hostgroup = dict(self.hostgroup_defaults)

        hostgroup['dn'] = 'cn={name},cn=hostgroups,cn=accounts,{suffix}'.format(
            name=name,
            suffix=self.basedn
        )
        hostgroup['cn'] = [name]
        hostgroup['member'] = [
            'fqdn={hostname},cn=computers,cn=accounts,{suffix}'.format(
                hostname=hostname,
                suffix=self.basedn
            ) for hostname in members
        ]
        hostgroup['member'].extend([
            'cn={name},cn=hostgroups,cn=accounts,{suffix}'.format(
                name=group,
                suffix=self.basedn
            ) for group in group_members
        ])

        return hostgroup

    def hostgroupname_generator(self, start, stop, step=1):
        for i in range(start, stop, step):
            yield 'hostgroup{}'.format(i)

    def gen_sudorule(
            self, name,
            user_members=(), usergroup_members=(),
            host_members=(), hostgroup_members=()
    ):
        sudorule = dict(self.sudo_defaults)

        sudorule['dn'] = 'ipaUniqueID=autogenerate,cn=sudorules,cn=sudo,{suffix}'.format(
            suffix=self.basedn
        )
        sudorule['cn'] = [name]

        sudorule['memberUser'] = [
            'uid={username},cn=users,cn=accounts,{suffix}'.format(
                username=user,
                suffix=self.basedn
            ) for user in user_members
        ]
        sudorule['memberUser'].extend([
            'cn={groupname},cn=groups,cn=accounts,{suffix}'.format(
                groupname=group,
                suffix=self.basedn
            ) for group in usergroup_members
        ])

        sudorule['memberHost'] = [
            'fqdn={hostname},cn=computers,cn=accounts,{suffix}'.format(
                hostname=host,
                suffix=self.basedn
            ) for host in host_members
        ]
        sudorule['memberHost'].extend([
            'cn={groupname},cn=hostgroups,cn=accounts,{suffix}'.format(
                groupname=group,
                suffix=self.basedn
            ) for group in hostgroup_members
        ])
        return sudorule

    def sudoname_generator(self, start, stop, step=1):
        for i in range(start, stop, step):
            yield 'sudo{}'.format(i)

    def gen_hbac(
            self, name,
            user_members=(), usergroup_members=(),
            host_members=(), hostgroup_members=()
    ):
        hbac = dict(self.hbac_defaults)

        hbac['dn'] = 'ipaUniqueID=autogenerate,cn=hbac,{suffix}'.format(
            suffix=self.basedn
        )
        hbac['cn'] = [name]

        hbac['memberUser'] = [
            'uid={username},cn=users,cn=accounts,{suffix}'.format(
                username=user,
                suffix=self.basedn
            ) for user in user_members
        ]
        hbac['memberUser'].extend([
            'cn={groupname},cn=groups,cn=accounts,{suffix}'.format(
                groupname=group,
                suffix=self.basedn
            ) for group in usergroup_members
        ])

        hbac['memberHost'] = [
            'fqdn={hostname},cn=computers,cn=accounts,{suffix}'.format(
                hostname=host,
                suffix=self.basedn
            ) for host in host_members
        ]
        hbac['memberHost'].extend([
            'cn={groupname},cn=hostgroups,cn=accounts,{suffix}'.format(
                groupname=group,
                suffix=self.basedn
            ) for group in hostgroup_members
        ])
        return hbac

    def hbacname_generator(self, start, stop, step=1):
        for i in range(start, stop, step):
            yield 'hbac{}'.format(i)

    def gen_users_and_groups(self):
        self.__gen_entries_with_groups(
            self.users,
            self.groups,
            self.groups_per_user,
            self.nested_groups_per_user,
            self.nested_groups_max_level,
            self.username_generator, self.gen_user,
            self.groupname_generator, self.gen_group
        )

    def gen_hosts_and_hostgroups(self):
        self.__gen_entries_with_groups(
            self.hosts,
            self.hostgroups,
            self.hostgroups_per_host,
            self.nested_hostgroups_per_host,
            self.nested_hostgroups_max_level,
            self.hostname_generator, self.gen_host,
            self.hostgroupname_generator, self.gen_hostgroup
        )

    def __gen_entries_with_groups(
            self,
            num_of_entries,
            num_of_groups,
            groups_per_entry,
            nested_groups_per_entry,
            max_nesting_level,
            gen_entry_name_f, gen_entry_f,
            gen_group_name_f, gen_group_f
    ):
        assert num_of_groups % groups_per_entry == 0
        assert num_of_groups >= groups_per_entry
        assert groups_per_entry > nested_groups_per_entry
        assert max_nesting_level > 0
        assert nested_groups_per_entry > 0
        assert (
            groups_per_entry - nested_groups_per_entry >
            int(math.ceil(nested_groups_per_entry / float(max_nesting_level)))
        ), (
            "At least {} groups is required to generate proper amount of "
            "nested groups".format(
                nested_groups_per_entry +
                int(
                    math.ceil(
                        nested_groups_per_entry / float(max_nesting_level)
                    )
                )
            )
        )

        for uid in gen_entry_name_f(0, num_of_entries):
            self.put_entry(gen_entry_f(uid))

        # create N groups per entry, <num_of_nested_groups> of them are nested
        #   User/Host (max nesting level = 2)
        #   |
        #   +--- G1 --- G2 (nested) --- G3 (nested, max level)
        #   |
        #   +--- G5 --- G6 (nested)
        #   |
        #   ......
        #   |
        #   +--- GN

        # how many members should be added to groups (set of groups_per_entry
        # have the same members)
        entries_per_group = num_of_entries // (num_of_groups // groups_per_entry)

        # generate groups and put users there
        for i in range(num_of_groups // groups_per_entry):

            uids = list(gen_entry_name_f(
                i * entries_per_group,
                (i + 1) * entries_per_group
            ))

            # per user
            last_grp_name = None
            nest_lvl = 0
            nested_groups_added = 0

            for group_name in gen_group_name_f(
                i * groups_per_entry,
                (i + 1) * groups_per_entry,
            ):
                # create nested groups first
                if nested_groups_added < nested_groups_per_entry:
                    if nest_lvl == 0:
                        # the top group
                        self.put_entry(
                            gen_group_f(
                                group_name,
                                members=uids
                            )
                        )
                        nest_lvl += 1
                        nested_groups_added += 1
                    elif nest_lvl == max_nesting_level:
                        # the last level group this group is not nested
                        self.put_entry(
                            gen_group_f(
                                group_name,
                                group_members=[last_grp_name],
                            )
                        )
                        nest_lvl = 0
                    else:
                        # mid level group
                        self.put_entry(
                            gen_group_f(
                                group_name,
                                group_members=[last_grp_name]
                            )
                        )
                        nested_groups_added += 1
                        nest_lvl += 1

                    last_grp_name = group_name
                else:
                    # rest of groups have direct membership
                    if nest_lvl != 0:
                        # assign the last nested group if exists
                        self.put_entry(
                            gen_group_f(
                                group_name,
                                members=uids,
                                group_members=[last_grp_name],
                            )
                        )
                        nest_lvl = 0
                    else:
                        self.put_entry(
                            gen_group_f(
                                group_name,
                                members=uids
                            )
                        )

    def generate_sudorules(self):
        self.__generate_entries_with_users_hosts_groups(
            self.direct_sudorules,
            self.indirect_sudorules,
            self.sudorules_per_user,
            self.sudorules_per_group,
            self.sudorules_per_host,
            self.sudorules_per_hostgroup,
            self.sudoname_generator, self.gen_sudorule
        )

    def generate_hbac(self):
        self.__generate_entries_with_users_hosts_groups(
            self.direct_hbac,
            self.indirect_hbac,
            self.hbac_per_user,
            self.hbac_per_group,
            self.hbac_per_host,
            self.hbac_per_hostgroup,
            self.hbacname_generator, self.gen_hbac
        )

    def __generate_entries_with_users_hosts_groups(
            self,
            num_of_entries_direct_members,
            num_of_entries_indirect_members,
            entries_per_user,
            entries_per_group,
            entries_per_host,
            entries_per_hostgroup,
            gen_entry_name_f, gen_entry_f,
    ):
        assert num_of_entries_direct_members % entries_per_user == 0
        assert num_of_entries_direct_members % entries_per_host == 0
        assert num_of_entries_indirect_members % entries_per_group == 0
        assert num_of_entries_indirect_members % entries_per_hostgroup == 0

        num_of_entries = num_of_entries_direct_members + num_of_entries_indirect_members

        # direct members
        users_per_entry = self.users // (num_of_entries_direct_members // entries_per_user)
        hosts_per_entry = self.hosts // (num_of_entries_direct_members // entries_per_host)

        start_user = 0
        stop_user = users_per_entry
        start_host = 0
        stop_host = hosts_per_entry
        for name in gen_entry_name_f(0, num_of_entries_direct_members):
            self.put_entry(
                gen_entry_f(
                    name,
                    user_members=self.username_generator(start_user, stop_user),
                    host_members=self.hostname_generator(start_host, stop_host)
                )
            )
            start_user = stop_user % self.users
            stop_user = start_user + users_per_entry
            stop_user = stop_user if stop_user < self.users else self.users

            start_host = stop_host % self.hosts
            stop_host = start_host + hosts_per_entry
            stop_host = stop_host if stop_host < self.hosts else self.hosts

        groups_per_entry = self.groups // (
            num_of_entries_indirect_members // entries_per_group
        )
        hostgroups_per_entry = self.hostgroups // (
            num_of_entries_indirect_members // entries_per_hostgroup
        )

        # indirect members
        start_group = 0
        stop_group = groups_per_entry
        start_hostgroup = 0
        stop_hostgroup = hostgroups_per_entry
        for name in gen_entry_name_f(num_of_entries_direct_members, num_of_entries):
            self.put_entry(
                gen_entry_f(
                    name,
                    usergroup_members=self.groupname_generator(start_group, stop_group),
                    hostgroup_members=self.hostgroupname_generator(start_hostgroup, stop_hostgroup)
                )
            )
            start_group = stop_group % self.groups
            stop_group = start_group + groups_per_entry
            stop_group = stop_group if stop_group < self.groups else self.groups

            start_hostgroup = stop_hostgroup % self.hostgroups
            stop_hostgroup = start_hostgroup + hostgroups_per_entry
            stop_hostgroup = stop_hostgroup if stop_hostgroup < self.hostgroups else self.hostgroups

    def do_magic(self):
        self.gen_users_and_groups()
        self.gen_hosts_and_hostgroups()
        self.generate_sudorules()
        self.generate_hbac()
        self.stream.close()


class IPADataLDIF(IPAData):

    def put_entry(self, entry):
        print(file=self.stream)
        print("dn: ", entry['dn'], file=self.stream)
        for k, values in entry.items():
            if k == 'dn':
                continue
            for v in values:
                print("{}: {}".format(k, v), file=self.stream)
        print(file=self.stream)


class IPATestDataLDIF(IPADataLDIF):
    def do_magic(self):
        self.gen_users_and_groups()

    def username_generator(self, start, stop, step=1, hostname=None):
        for i in range(start, stop, step):
            yield 'user%d%s' % (i, hostname)

    def hostname_generator(self, start, stop, step=1):
        for i in range(start, stop, step):
            yield '{}{:03d}.{}'.format(
                self.host_prefix, i, self.domain
            )

    def gen_users_and_groups(self):
        for host in self.hostname_generator(0, self.hosts):
            for uid in self.username_generator(0, self.users,
                                               hostname=host):
                self.put_entry(self.gen_user(uid))

    def put_entry(self, entry):
        print(file=self.stream)
        print("dn: ", entry['dn'], file=self.stream)
        for k, values in entry.items():
            if k == 'dn':
                continue
            for v in values:
                print("{}: {}".format(k, v), file=self.stream)
        print(file=self.stream)


@click.command("cli", context_settings={"show_default": True})
@click.option("--users-per-host", default=10,
              help="Number of users to create for each host.",
              type=int)
@click.option("--hosts", default=500, help="Number of hosts to create.",
              type=int)
@click.option("--host-prefix", default="client", help="hostname prefix")
@click.option("--outfile", default=None, help="LDIF output file")
@click.option("--with-groups", default=False, help="Create user groups.",
              is_flag=True)
@click.option("--with-hostgroups", default=False, help="Create host groups.",
              is_flag=True)
@click.option("--with-sudo", default=False, help="Create sudo rules.",
              is_flag=True)
@click.option("--with-hbac", default=False, help="Create hbac rules.",
              is_flag=True)
@click.option("--debug", default=False, help="Debug logging", is_flag=True)
def main(
    users_per_host,
    hosts,
    host_prefix,
    with_groups,
    with_hostgroups,
    with_sudo,
    with_hbac,
    debug,
    outfile,
):
    api.bootstrap(in_server=True, context='server', in_tree=False, debug=debug)
    api.finalize()
    data = IPATestDataLDIF(
        api.env.domain,
        api.env.basedn,
        api.env.realm,
        users=users_per_host,
        hosts=hosts,
        host_prefix=host_prefix,
        outfile=outfile,
    )
    data.do_magic()


if __name__ == '__main__':
    main()
