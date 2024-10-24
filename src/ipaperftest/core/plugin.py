#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import subprocess as sp
import os
import uuid
import time
import tarfile
import queue
import ansible_runner
from datetime import datetime

from ipaperftest.core.constants import (
    SUCCESS,
    ERROR,
    ANSIBLE_REPLICA_INSTALL_PLAYBOOK,
    ANSIBLE_SERVER_ADD_REPO_PLAYBOOK,
    getLevelName,
    HOSTS_FILE_TEMPLATE,
    ANSIBLE_CFG_TEMPLATE,
    ANSIBLE_SERVER_CONFIG_PLAYBOOK,
    ANSIBLE_REPLICA_CONFIG_PLAYBOOK,
    ANSIBLE_ENABLE_DATA_COLLECTION_PLAYBOOK,
    ANSIBLE_FETCH_FILES_PLAYBOOK,
)
from ipaperftest.providers.idmci import IdMCIProvider
from ipaperftest.providers.vagrant import VagrantProvider


class Registry:
    """
    A decorator that makes plugins available to the API

    Usage::

        register = Registry()

        @register()
        class some_plugin(...):
            ...
    """
    def __init__(self):
        self.plugins = []

    def __call__(self, cls):
        if not callable(cls):
            raise TypeError('plugin must be callable; got %r' % cls)
        self.plugins.append(cls)
        return cls

    def get_plugins(self):
        for plugincls in self.plugins:
            yield plugincls(self)


class Plugin:
    """
    Base class for all plugins.

    registry defines where the plugin was registered, normally via
    a pkg_resource.

    Usage::

        register = Registry()

        @register()
        test_foo(Plugin)
            def run(self):
               ...

    """
    def __init__(self, registry):
        self.registry = registry
        self.domain = "ipa.test"
        self.custom_logs = []
        self.provider = None

    def run_ansible_playbook_from_template(self, template, filename, playbook_args, ctx):
        """
        The playbook must be passed as a string template.
        It will be written into a file under the sync directory
        using the filename passed.

        Arguments must be passed as a dictionary.
        """

        playbook_str = template.format(**playbook_args)
        playbook_path = "runner_metadata/" + filename + ".yml"
        with open(playbook_path, "w") as f:
            f.write(playbook_str)

        ret = ansible_runner.run(private_data_dir="runner_metadata",
                                 playbook=filename + ".yml",
                                 verbosity=1)

        return ret

    def run_ssh_command(self, command, target, ctx, wait=True):
        """
        SSH into the specified host target and run the command passed.
        """

        cmd = ("ssh -i '{}' -i '{}' root@{} "
               "-o StrictHostKeyChecking=no "
               "-o UserKnownHostsFile=/dev/null "
               "\"{}\"").format(ctx.params["private_key"],
                                self.provider.default_private_key, target, command)
        func = sp.run if wait else sp.Popen

        return func(cmd, shell=True, cwd="runner_metadata",
                    stdout=sp.PIPE, stdin=sp.DEVNULL, stderr=sp.PIPE)

    def select_provider(self, ctx):
        selected_provider = ctx.params["provider"].lower()
        if selected_provider == "vagrant":
            self.provider = VagrantProvider()
        elif selected_provider == "idmci":
            self.provider = IdMCIProvider()
        else:
            raise RuntimeError("Selected provider '%s' does not exist." % selected_provider)

    def generate_clients(self, ctx):
        # A generator to yield client configurations which will be
        # appended to the list of machine configs.
        yield None

    def reset_sync_folder(self, ctx):
        """Clear up any previously synced data and prepare for new data"""
        sp.run(["rm", "-rf", "sync"], stdout=sp.PIPE)
        sp.run(["mkdir", "sync"], stdout=sp.PIPE)

    def reset_metadata_folder(self, ctx):
        """Clear up metadata from previous executions"""
        sp.run(["rm", "-rf", "runner_metadata"], stdout=sp.PIPE)
        sp.run(["mkdir", "runner_metadata"], stdout=sp.PIPE)

    def clone_ansible_freeipa(self, ctx):
        """ Clone ansible-freeipa upstream and create the Ansible config"""
        sp.run(
            [
                "git",
                "clone",
                "--depth=1",
                "--branch",
                "v1.13.2",
                "https://github.com/freeipa/ansible-freeipa.git",
            ],
            cwd="runner_metadata",
            stdout=sp.PIPE,
        )
        with open("runner_metadata/ansible.cfg", "w") as f:
            f.write(ANSIBLE_CFG_TEMPLATE.format(
                cwd=os.path.join(os.getcwd(), "runner_metadata"),
                private_key_path=ctx.params["private_key"] or self.provider.default_private_key,
                default_private_key_path=self.provider.default_private_key
                )
            )

    def generate_metadata(self, ctx):

        machine_configs = [
            {
                "hostname": "server.%s" % self.domain.lower(),
                "type": "server"
            }
        ]

        for i in range(ctx.params['replicas']):
            name = "replica{}".format(str(i))
            machine_configs.append(
                {
                    "hostname": "%s.%s" % (name, self.domain.lower()),
                    "type": "server"
                }
            )

        for c in self.generate_clients(ctx):
            if c:
                machine_configs.append(c)

        self.provider.generate_metadata(ctx, machine_configs, self.domain)

    def generate_ansible_inventory(self, ctx):
        # Each replica should have a maximum of 4 agreements, defined in tiers.
        # Top node will have 4 childs, while every other node will have 3 children
        # + 1 parent.
        def generate_replica_lines():
            def build_replica_tree(d={}, current_node="server", n_nodes=0, q=queue.Queue()):
                n_children = 4 if d == {} else 3
                for _ in range(n_children):
                    if current_node not in d.keys():
                        d[current_node] = [f"replica{n_nodes}"]
                    else:
                        d[current_node].append(f"replica{n_nodes}")
                    n_nodes += 1
                    if n_nodes == ctx.params["replicas"]:
                        return d
                for c in d[current_node]:
                    q.put(c)
                return build_replica_tree(d, q.get(), n_nodes, q)

            def get_replica_tiers(tree, tiers=[]):
                if tiers == []:
                    # first tier is just original server
                    tiers.append(["server"])
                    return get_replica_tiers(tree, tiers)
                else:
                    # next tier is all children of last added tier
                    last_tier = tiers[-1]
                    new_tier = []
                    for replica in last_tier:
                        try:
                            for child in tree[replica]:
                                new_tier.append(child)
                        except KeyError:
                            # this is a leaf node
                            continue
                    if new_tier == []:
                        return tiers
                    tiers.append(new_tier)
                    return get_replica_tiers(tree, tiers)

            def get_replica_parent(tree, child):
                for parent, children in tree.items():
                    if child in children:
                        return parent

            tree = build_replica_tree()
            tiers = get_replica_tiers(tree)
            replica_lines = []
            ipareplicas_group_lines = ["\n[ipareplicas:children]"]
            for i, tier in enumerate(tiers[1:]):
                ipareplicas_group_lines.append(f"ipareplicas_tier{i}")
                # Slice tier0 as it's just the original server
                tier_lines = [
                    f"[ipareplicas_tier{i}]"
                ]
                for replica in tier:
                    replica_ip = self.provider.hosts[replica]
                    parent = get_replica_parent(tree, replica)
                    tier_lines.append(f"{replica_ip} ipareplica_servers={parent}.{self.domain}")
                replica_lines.extend(tier_lines)
            replica_lines.extend(ipareplicas_group_lines)
            return replica_lines

        replica_lines = (generate_replica_lines()
                         if ctx.params["replicas"] > 0
                         else ["[ipareplicas]"])
        inventory_str = HOSTS_FILE_TEMPLATE.format(
            server_ip=self.provider.hosts["server"],
            domain=self.domain.lower(),
            realm=self.domain.upper(),
            client_ips="\n".join(
                [ip for name, ip in self.provider.hosts.items() if name.startswith("client")]
            ),
            replica_lines="\n".join(replica_lines),
            windows_ips="\n".join(
                [ip for name, ip in self.provider.hosts.items() if name.startswith("windows")]
            ),
            windows_admin_password=self.provider.windows_admin_password
        )
        with open("runner_metadata/inventory", "w") as f:
            f.write(inventory_str)

    def ansible_ping(self, ctx):
        print("Sending ping to VMs...")
        ansible_runner.run(private_data_dir="runner_metadata",
                           host_pattern="ipaserver,ipaclients,ipareplicas*",
                           module="ping")
        if ctx.params["ad_threads"] > 0:
            ansible_runner.run(private_data_dir="runner_metadata",
                               host_pattern="windows",
                               module="win_ping")

    def configure_server(self, ctx):
        if ctx.params["custom_repo_url"]:
            args = {
                "repo_url": ctx.params["custom_repo_url"]
            }
            self.run_ansible_playbook_from_template(ANSIBLE_SERVER_ADD_REPO_PLAYBOOK,
                                                    "add_custom_repo", args, ctx)
        etc_hosts = ("\n" + " " * 10).join(
            [f"{ip} {host}.{self.domain}" for host, ip in self.provider.hosts.items()])
        args = {
            "server_ip": self.provider.hosts["server"],
            "domain": self.domain,
            "etchosts": etc_hosts
        }
        self.run_ansible_playbook_from_template(ANSIBLE_SERVER_CONFIG_PLAYBOOK,
                                                "server_config", args, ctx)

    def configure_replicas(self, ctx):
        args = {
            "server_ip": self.provider.hosts["server"],
        }
        self.run_ansible_playbook_from_template(ANSIBLE_REPLICA_CONFIG_PLAYBOOK,
                                                "replica_config", args, ctx)

    def install_server(self, ctx):
        print("Installing IPA server...")
        ansible_runner.run(private_data_dir="runner_metadata",
                           playbook="ansible-freeipa/playbooks/install-server.yml",
                           verbosity=1)

    def install_replicas(self, ctx):
        if ctx.params['replicas'] > 0:
            print("Installing IPA replicas...")
            self.run_ansible_playbook_from_template(ANSIBLE_REPLICA_INSTALL_PLAYBOOK,
                                                    "replica_install", {}, ctx)

    def enable_data_collection(self, ctx):
        print("Starting monitoring on server using SAR...")
        self.run_ansible_playbook_from_template(ANSIBLE_ENABLE_DATA_COLLECTION_PLAYBOOK,
                                                "enable_data_collection", {}, ctx)

    def collect_logs(self, ctx):
        def add_logs(logs):
            for log in logs:
                yield '        - "{}"'.format(log)

        # Wait for sar to analyze system
        print("Waiting before copying logs...")
        time.sleep(60)

        print("Copying logs into sync folder...")
        for host in self.provider.hosts.keys():
            sp.run(["mkdir", "-p", f"sync/{host}"], stdout=sp.PIPE)

        logstr = '\n'.join(add_logs(self.custom_logs))

        args = {
            "cwd": os.getcwd(),
            "custom_logs": logstr
        }
        self.run_ansible_playbook_from_template(ANSIBLE_FETCH_FILES_PLAYBOOK,
                                                "fetch_logs", args, ctx)

    def post_process_logs(self, ctx):
        """Analyze log files for failures, patterns, etc"""
        pass

    def check_results(self, ctx):
        """ Compare results to expected results """
        expected_result_type = ctx.params["expected_result_type"]
        if expected_result_type == "no_errors":
            return

        expected_result = ctx.params["expected_result"]
        if expected_result_type == "time":
            result = self.execution_time
        elif expected_result_type == "time_unit":
            result = self.execution_time / ctx.params["amount"]

        if result > expected_result:
            yield Result(self, ERROR,
                         error="The test took longer than expected. Expected (%s): %s, got: %s"
                         % (expected_result_type, expected_result, result))
        else:
            yield Result(self, SUCCESS,
                         msg="The test completed in the expected (%s) time (%s)."
                         % (expected_result_type, result))

    def archive_results(self, ctx):
        """ Create tar with logs and metadata"""
        with tarfile.open(self.results_archive_name + ".tar.gz", "w:gz") as tar:
            files_to_add = [
                "sync/",
                "runner_metadata",
            ]
            files_to_add.extend(self.provider.files_to_log)
            for f in files_to_add:
                tar.add(f)

    def validate_options(self, ctx):
        pass

    def run(self, ctx):
        pass

    def execute(self, ctx):
        self.select_provider(ctx)

        funcs = [
            self.validate_options,
            self.provider.check_requirements,
            self.provider.cleanup,
            self.reset_sync_folder,
            self.reset_metadata_folder,
            self.clone_ansible_freeipa,
            self.provider.setup,
            self.generate_metadata,
            self.provider.create_vms,
            self.provider.collect_hosts,
            self.generate_ansible_inventory,
            self.ansible_ping,
            self.configure_server,
            self.configure_replicas,
            self.install_server,
            self.install_replicas,
            self.enable_data_collection,
            self.run,
            self.collect_logs,
            self.post_process_logs,
            self.check_results,
        ]

        for func in funcs:
            try:
                yield from func(ctx)
            except TypeError:
                # nothing to yield from in func
                pass


class Result:
    """
    The result of a test.

    :param plugin: The plugin which generated the result.
    :param result: A result constant representing the level of error.
    :param source: If no plugin is passed then the name of the source
                   can be provided directly.
    :param test: If no plugin is passed then the name of the test
                   can be provided directly.
    :param kw: A dictionary of items providing insight in the error.

    Either both test and source need to be provided or plugin needs
    to be provided.

    kw is meant to provide some level of flexibility to test authors
    but the following is a set of pre-defined keys that may be present:

        key: some test can have multiple tests. This
             provides for uniqueuess.
        msg: A message that can take other keywords as input
        exception: used when a test raises an exception
    """
    def __init__(self, plugin, result, source=None, test=None,
                 start=None, duration=None, when=None, **kw):
        self.result = result
        self.kw = kw
        self.when = when
        self.duration = duration
        self.uuid = str(uuid.uuid4())
        if None not in (test, source):
            self.test = test
            self.source = source
        else:
            if plugin is None:
                raise TypeError('source and test or plugin must be provided')
            self.test = plugin.__class__.__name__
            self.source = plugin.__class__.__module__
        if start is not None:
            dur = datetime.utcnow() - start
            self.duration = '%6.6f' % dur.total_seconds()

        assert getLevelName(result) is not None

    def __repr__(self):
        return "%s.%s(%s): %s" % (self.source, self.test, self.kw,
                                  self.result)


class Results:
    """
    A list-like collection of Result values.

    Provides a very limited subset of list operations. Is intended for
    internal-use only and not by test functions.

    Usage::

        results = Results()

        result = Result(plugin, SUCCESS, **kw)
        results.add(result)
    """
    def __init__(self):
        self.results = []

    def __len__(self):
        return len(self.results)

    def add(self, result):
        assert isinstance(result, Result)
        self.results.append(result)

    def extend(self, results):
        assert isinstance(results, Results)
        self.results.extend(results.results)

    def output(self):
        for result in self.results:
            yield dict(source=result.source,
                       test=result.test,
                       result=getLevelName(result.result),
                       uuid=result.uuid,
                       when=result.when,
                       duration=result.duration,
                       kw=result.kw)
