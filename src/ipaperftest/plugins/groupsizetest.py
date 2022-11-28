#
# Copyright (C) 2022 FreeIPA Contributors see COPYING for license
#

import subprocess as sp
from datetime import datetime

from ipaperftest.core.constants import ANSIBLE_GROUPSIZETEST_SERVER_CONFIG_PLAYBOOK
from ipaperftest.core.plugin import Plugin
from ipaperftest.plugins.registry import registry


@registry
class GroupSizeTest(Plugin):

    def __init__(self, registry):
        super().__init__(registry)
        self.custom_logs = ["~/*group_add_member.log", ]

    def generate_clients(self, ctx):
        yield ()

    def run(self, ctx):
        # TODO: this should be moved to a resources folder
        sp.run(["cp", "create-test-data.py", "runner_metadata/"])

        # Configure server before execution
        args = {
            "threads": ctx.params["threads"],
            "sizelimit": ctx.params["sizelimit"]
        }
        self.run_ansible_playbook_from_template(
            ANSIBLE_GROUPSIZETEST_SERVER_CONFIG_PLAYBOOK,
            "authenticationgroupsize_server_config", args, ctx
        )

        self.run_ssh_command("echo password | kinit admin", self.provider.hosts["server"], ctx)
        self.run_ssh_command("ipa user-add --first tim --last user tuser1",
                             self.provider.hosts["server"], ctx)

        command = "ipa group-add-member --users tuser1 allusers"
        cmd = (
            r"echo {cmd} > ~/group_add_member.log;"
            r"/usr/bin/time -p {cmd} >> ~/group_add_member.log 2>&1;"
            r"echo $? >> ~/group_add_member.log".format(
                cmd=command
            )
        )
        self.run_ssh_command(cmd, self.provider.hosts["server"], ctx)

        return

    def post_process_logs(self, ctx):
        """  """
        with open("sync/server/group_add_member.log", "r") as fd:
            lines = fd.readlines()

        addtime = None
        for line in lines:
            if line.startswith("real "):
                addtime = line.split()[1]
                break

        self.results_archive_name = "GroupTest-{}-{}-{}threads-{}sizelimit-{}real".format(
            datetime.now().strftime("%FT%H%MZ"),
            self.provider.server_image.replace("/", ""),
            ctx.params["threads"],
            ctx.params["sizelimit"],
            addtime
        )
