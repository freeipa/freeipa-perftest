#
# Copyright (C) 2022 FreeIPA Contributors see COPYING for license
#

class Provider:
    """
    Base class for different providers used during test execution
    """

    def __init__(self):
        self.files_to_log = []
        self.server_image = ""
        self.client_image = ""
        self.windows_admin_password = ""
        self.default_private_key = ""  # path relative to runner_metadata
        self.hosts = {}  # host:ip dictionary

    def check_requirements(self, ctx):
        pass

    def cleanup(self, ctx):
        pass

    def setup(self, ctx):
        pass

    def generate_metadata(self, ctx, machine_configs, domain):
        pass

    def create_vms(self, ctx):
        pass

    def collect_hosts(self, ctx):
        pass
