#
# Copyright (C) 2022 FreeIPA Contributors see COPYING for license
#

import os
import subprocess as sp
from ipaperftest.core.constants import IDMCI_HOST_TEMPLATE, IDMCI_METADATA_TEMPLATE
from ipaperftest.providers.provider import Provider


class IdMCIProvider(Provider):
    """
    IdM-CI provider. This uses Red Hat's internal infrastructure so
    authentication is needed.
    """

    def __init__(self):
        super().__init__()
        self.default_private_key = "config/id_rsa"
        self.windows_admin_password = "Secret123"

    def check_requirements(self):
        path = os.path.join(os.path.expanduser('~'), ".idmci-ansible-vault-password-file")
        if not os.path.exists(path):
            raise RuntimeError("Ansible Vault Password file "
                  "(~/.idmci-ansible-vault-password-file) is not present.")

    def cleanup(self, ctx):
        """We clean up *before* an execution so that the VMs remain.

           This is so we can evaluate what, if anything, went wrong.
        """

        if not os.path.exists("runner_metadata"):
            return

        sp.run(["python3", "idm-ci/scripts/te", "--phase", "teardown", "metadata.yaml"],
               cwd="runner_metadata",
               env=dict(os.environ,
                        ANSIBLE_VAULT_PASSWORD_FILE="~/.idmci-ansible-vault-password-file"))

    def setup(self, ctx):
        sp.run(["git", "clone", "--depth=1",
                "https://gitlab.cee.redhat.com/identity-management/idm-ci.git"],
               cwd="runner_metadata", stdout=sp.PIPE)

    def generate_metadata(self, ctx, machine_configs, domain):
        """Create the metadata file

           This directly controls creating the entries for the server
           and replicas. A per-test generator is used to generate the
           client entries.
        """

        # IdM-CI specific host types
        types = {
            "server": "ipalarge",
            "client": "ipaclient",
            "ad": "ad"
        }

        server_img = ctx.params["server_image"]
        client_img = ctx.params["client_image"]
        self.server_image = server_img if server_img else "fedora-34"
        self.client_image = client_img if client_img else "fedora-34"

        images = {
            "server": self.server_image,
            "client": self.client_image,
            "ad": "win-2019",
        }

        hosts_metadata = ""
        for conf in machine_configs:
            hosts_metadata += IDMCI_HOST_TEMPLATE.format(
                hostname=conf['hostname'],
                group=types[conf['type']],
                os=images[conf['type']]
            )

        file_contents = IDMCI_METADATA_TEMPLATE.format(
            domain=domain.lower(),
            hosts=hosts_metadata,
            lifetime=ctx.params['idmci_lifetime']
        )
        with open("runner_metadata/metadata.yaml", "w") as f:
            f.write(file_contents)

    def create_vms(self, ctx):
        print("Creating machines...")
        sp.run(["python3", "idm-ci/scripts/te", "--upto", "prep", "metadata.yaml"],
               cwd="runner_metadata",
               env=dict(os.environ,
                        ANSIBLE_VAULT_PASSWORD_FILE="~/.idmci-ansible-vault-password-file"))

    def collect_hosts(self, ctx):
        """Collect IP information on the configured hosts in a dict

           hostname:ip
        """
        mrack_output = sp.run(["mrack", "list"],
                              stderr=sp.PIPE, cwd="runner_metadata").stderr.decode("utf-8")
        # mrack list output example:
        # active fedora-34 41df92f5-5f47-426a-9267-47758d6b9098 fedora34.idmci.test 10.0.199.6 None None  # noqa: E501
        for line in mrack_output.splitlines():
            info = line.split(" ")
            name = info[3].split(".")[0]  # don't include full domain
            self.hosts[name] = info[4]
