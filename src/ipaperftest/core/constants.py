#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

# flake8: noqa
# Error reporting result
SUCCESS = 0
WARNING = 10
ERROR = 20
CRITICAL = 30

_levelToName = {
    SUCCESS: 'SUCCESS',
    WARNING: 'WARNING',
    ERROR: 'ERROR',
    CRITICAL: 'CRITICAL',
}

_nameToLevel = {
    'SUCCESS': SUCCESS,
    'WARNING': WARNING,
    'ERROR': ERROR,
    'CRITICAL': CRITICAL,
}


def getLevelName(level):
    """
    Translate between level constants and their textual mappings.

    If the level is one of the predefined levels then returns the
    corresponding string.

    If a numeric value corresponding to one of the defined levels
    is passed in instead the corresponding string representation is
    returned.
    """
    name = _levelToName.get(level) or _nameToLevel.get(level)
    if name is not None:
        return name

    return level

IDMCI_METADATA_TEMPLATE = """
domains:
  - name: {domain}
    type: IPA
    hosts:
    {hosts}

phases:
- name: init
  steps:
  - playbook: init/testrunner-dir.yaml
- name: provision
  steps:
  - extra_vars:
      lifetime: {lifetime}
    playbook: provision/mrack-up.yaml
- name: prep
  steps:
  - playbook: prep/redhat-base.yaml
  - playbook: prep/repos.yaml
- name: teardown
  steps:
  - playbook: teardown/mrack-destroy.yaml
"""

IDMCI_HOST_TEMPLATE = """
    - name: {hostname}
      group: {group}
      os: {os}
"""

VAGRANTFILE_TEMPLATE = """
    Vagrant.configure("2") do |config|
        config.vm.synced_folder ".", "/vagrant", disabled: true
        config.vm.provider :libvirt do |libvirt|
            # Disabling QEMU Session as it causes issues with private network
            # https://fedoraproject.org/wiki/Changes/Vagrant_2.2_with_QEMU_Session
            libvirt.qemu_use_session = false
            libvirt.management_network_address = "192.168.3.0/16"
        end
        {vagrant_additional_config}
        {machine_configs}
    end
"""

VAGRANT_HOST_TEMPLATE = """
    config.vm.define :{machine_name} do |{machine_name}|
        {machine_name}.vm.provider "libvirt" do |v|
            v.memory = {memory}
            v.cpus = {cpus}
        end
        {machine_name}.vm.box = "{box}"
        {machine_name}.vm.hostname = "{hostname}"
        {machine_name}.vm.network "private_network", libvirt__netmask: "255.255.0.0", ip: "{ip}"
        {extra_options}
    end
"""

HOSTS_FILE_TEMPLATE = """
[ipaserver]
{server_ip}

[ipaserver:vars]
ipaadmin_password=password
ipadm_password=password
ipaserver_domain={domain}
ipaserver_realm={realm}
ipaserver_setup_dns=yes
ipaserver_auto_forwarders=yes
ipaserver_auto_reverse=yes
ipaserver_setup_adtrust=yes
ipaserver_no_dnssec_validation=yes

{replica_lines}

[ipareplicas:vars]
ipaadmin_password=password
ipadm_password=password
ipareplica_domain={domain}
ipaserver_realm={realm}
ipareplica_setup_dns=yes
ipareplica_setup_ca=yes
ipareplica_auto_forwarders=yes
ipareplica_auto_reverse=yes

[ipaclients]
{client_ips}

[ipaclients:vars]
ipaadmin_password=password
ipaserver_domain={domain}
ipaserver_realm={realm}
ipaadmin_password=password
ipasssd_enable_dns_updates=yes
ipaclient_no_nisdomain=yes

[windows]
{windows_ips}

[windows:vars]
ansible_connection=winrm
ansible_port=5986
ansible_user=Administrator
ansible_password={windows_admin_password}
ansible_winrm_server_cert_validation=ignore
ansible_winrm_operation_timeout_sec=60
ansible_winrm_read_timeout_sec=70
"""


ANSIBLE_CFG_TEMPLATE = """
[defaults]
remote_user = root
host_key_checking = False
deprecation_warnings = False
roles_path   = {cwd}/ansible-freeipa/roles
library      = {cwd}/ansible-freeipa/plugins/modules
module_utils = {cwd}/ansible-freeipa/plugins/module_utils
[ssh_connection]
ssh_args = '-i "{private_key_path}" -i "{default_private_key_path}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -C -o ControlMaster=auto -o ControlPersist=60s'
"""

ANSIBLE_FETCH_FILES_PLAYBOOK = """
---
- name: Fetch IPA server log files
  hosts: ipaserver, ipareplicas*
  become: yes
  ignore_errors: yes
  tasks:
    - synchronize:
        src: "{{{{ item }}}}"
        dest: "{cwd}/sync/{{{{ ansible_hostname }}}}/"
        mode: pull
        use_ssh_args: yes
      with_items:
        - "/var/log/ipaserver-install.log"
        - "/var/log/ipaclient-install.log"
        - "/var/log/httpd"
        - "/var/log/dirsrv"
        - "/var/log/krb5kdc.log"
        - "/var/log/pki/pki-tomcat/ca"
        - "~/saroutput"
{custom_logs}

- name: Fetch IPA replica log files
  hosts: ipareplicas
  become: yes
  tasks:
    - synchronize:
        src: "{{{{ item }}}}"
        dest: "{cwd}/sync/{{{{ ansible_hostname }}}}/"
        mode: pull
        use_ssh_args: yes
      with_items:
>>>>>>> c497105 (Retrieve any custom logs from the server as well)
        - "/var/log/ipareplica-install.log"
        - "/var/log/httpd"
        - "/var/log/dirsrv"
        - "/var/log/krb5kdc.log"
        - "/var/log/pki/pki-tomcat/ca"
        - "~/saroutput"

- name: Fetch IPA clients log files
  hosts: ipaclients
  become: yes
  ignore_errors: yes
  tasks:
    - synchronize:
        src: "{{{{ item }}}}"
        dest: "{cwd}/sync/{{{{ ansible_hostname }}}}/"
        mode: pull
        use_ssh_args: yes
      with_items:
        - "/var/log/ipaclient-install.log"
{custom_logs}

"""

ANSIBLE_SERVER_ADD_REPO_PLAYBOOK = """
---
- name: Add repo to server hosts
  hosts: ipaserver, ipareplicas*
  become: yes
  tasks:
    - copy:
        dest: /etc/yum.repos.d/freeipa-perftest-custom.repo
        content: |
          [freeipa-perftest-additional-repo]
          name = Custom repo added by freeipa-perftest
          baseurl = {repo_url}
          enabled = 1
          gpgcheck = 0
          priority = 1
          module_hotfixes = true
"""

ANSIBLE_SERVER_CONFIG_PLAYBOOK = """
---
- name: Configure server before installation
  hosts: ipaserver, ipareplicas*
  become: yes
  tasks:
    - sysctl:
        name: net.ipv6.conf.all.disable_ipv6
        value: '0'
        sysctl_set: yes
    - blockinfile:
        path: /etc/hosts
        block: |
          {etchosts}
    - package:
        name: sysstat
"""

ANSIBLE_REPLICA_CONFIG_PLAYBOOK = """
---
- name: Configure replicas before installation
  hosts: ipareplicas*
  become: yes
  tasks:
    - lineinfile:
        path: /etc/resolv.conf
        line: nameserver {server_ip}
"""

ANSIBLE_REPLICA_INSTALL_PLAYBOOK = """
---
- name: Install IPA replicas (tier0)
  hosts: ipareplicas_tier0
  become: true

  roles:
  - role: ipareplica
    state: present

- name: Install IPA replicas (tier1)
  hosts: ipareplicas_tier1
  become: true

  roles:
  - role: ipareplica
    state: present

- name: Install IPA replicas (tier2)
  hosts: ipareplicas_tier2
  become: true

  roles:
  - role: ipareplica
    state: present

- name: Install IPA replicas (tier3)
  hosts: ipareplicas_tier3
  become: true

  roles:
  - role: ipareplica
    state: present
"""

ANSIBLE_ENABLE_DATA_COLLECTION_PLAYBOOK = """
---
- name: Enable data collection using SAR
  hosts: ipaserver, ipareplicas*
  tasks:
    - shell:
        cmd: "nohup sar -o ~/saroutput 2 >/dev/null 2>&1 &"
"""

ANSIBLE_ENROLLMENTTEST_CLIENT_CONFIG_PLAYBOOK = """
---
- name: Configure client machines before installation
  hosts: ipaclients
  become: yes
  tasks:
    - lineinfile:
        path: /etc/resolv.conf
        regexp: ".*"
        state: absent
    - lineinfile:
        path: /etc/resolv.conf
        line: nameserver {server_ip}
    - lineinfile:
        path: /etc/hosts
        line: {server_ip} server.{domain} server
    - package:
        name: ipa-client
"""

ANSIBLE_COUNT_IPA_HOSTS_PLAYBOOK = """
---
- name: Count hosts registered in IPA server
  hosts: ipaserver
  tasks:
    - command: "kinit admin"
      args:
        stdin: "password"
    - shell:
        cmd: "ipa host-find --sizelimit=0 | grep 'Host name:' | wc -l"
      register: host_find_output
    - set_fact:
        host_find_output: "{{{{ host_find_output.stdout }}}}"
        cacheable: yes
"""

ANSIBLE_APITEST_CLIENT_CONFIG_PLAYBOOK = """
---
- name: Configure client machines before installation
  hosts: ipaclients
  become: yes
  tasks:
    - lineinfile:
        path: /etc/resolv.conf
        regexp: ".*"
        state: absent
    - lineinfile:
        path: /etc/resolv.conf
        line: nameserver {server_ip}
    - lineinfile:
        path: /etc/hosts
        line: {server_ip} server.{domain} server
    - package:
        name: at
    - systemd:
        name: atd
        enabled: yes
        state: started
"""

ANSIBLE_APITEST_CLIENT_UPLOAD_SEQUENTIAL_SCRIPT_PLAYBOOK = """
---
- name: Upload script with commands to execute sequentially
  hosts: ipaclients
  become: yes
  tasks:
    - synchronize:
        src: "{{{{ item }}}}"
        dest: "/root"
        mode: push
        use_ssh_args: yes
      with_items:
        - apitest_sequential_commands.sh
"""

ANSIBLE_AUTHENTICATIONTEST_SERVER_CONFIG_PLAYBOOK = """
---
- name: Configure server before execution
  hosts: ipaserver
  become: yes
  tasks:
    - synchronize:
        src: "{{{{ item }}}}"
        dest: "/root"
        mode: push
        use_ssh_args: yes
      with_items:
        - create-test-data.py
        - set-password.py
    - package:
        name: python3-pip
    - command:
        cmd: "pip3 install click"
    - command:
        cmd: "python3 create-test-data.py --hosts {amount} --outfile userdata.ldif --users-per-host {threads}"
        chdir: /root
    - ipaconfig:
        ipaadmin_password: password
        enable_migration: yes
    - command:
        cmd: "ldapadd -x -D 'cn=Directory Manager' -w password -f userdata.ldif"
        chdir: /root
    - command:
        cmd: "python3 set-password.py --dm-password password --hosts {amount} --users-per-host {threads}"
        chdir: /root
    - ipaconfig:
        ipaadmin_password: password
        enable_migration: no
"""

ANSIBLE_AUTHENTICATIONTEST_CLIENT_CONFIG_PLAYBOOK = """
---
- name: Configure clients before installation
  hosts: ipaclients
  become: yes
  tasks:
    - yum_repository:
        name: freeipa_freeipa-perftest-copr-repo
        baseurl: https://download.copr.fedorainfracloud.org/results/@freeipa/freeipa-perftest/fedora-$releasever-$basearch/
        gpgkey: https://download.copr.fedorainfracloud.org/results/@freeipa/freeipa-perftest/pubkey.gpg
        description: "Copr repo for freeipa-perftest owned by @freeipa"
    - package:
        name: freeipa-perftest-client
        state: present
      retries: 5
      delay: 3
      register: result
      until: result.rc == 0
    - package:
        name: ipa-client
    - file:
        path: /etc/systemd/resolved.conf.d
        state: directory
    - copy:
        dest: /etc/systemd/resolved.conf.d/dns.conf
        content: |
          [Resolve]
          DNS={server_ip}
          Domains=~.
    - systemd:
        name: systemd-resolved
        state: restarted
        daemon-reload: yes
    - lineinfile:
        path: /etc/hosts
        line: {server_ip} server.{domain} server
    - lineinfile:
        path: /etc/pam.d/login
        regexp: "\\\\.*pam_loginuid.so"
        state: absent
"""

ANSIBLE_AUTHENTICATIONTEST_AD_SERVER_CONFIG_PLAYBOOK = """
---
- name: Setup Active Directory
  hosts: windows
  tasks:
    - win_firewall_rule:
        name: Allow access from our network
        direction: in
        action: allow
        enabled: yes
        state: present
    - win_feature:
        name: '{{{{ item }}}}'
        include_management_tools: yes
        include_sub_features: yes
        state: present
      with_items:
      - AD-Domain-Services
      - DNS
    - win_shell: |
        Import-Module ADDSDeployment

        Install-ADDSForest                                                        \\
          -DomainName "ad.test"                                                   \\
          -CreateDnsDelegation:$false                                             \\
          -DomainNetbiosName "AD"                                                 \\
          -ForestMode "WinThreshold"                                              \\
          -DomainMode "WinThreshold"                                              \\
          -Force:$true                                                            \\
          -InstallDns:$true                                                       \\
          -NoRebootOnCompletion:$true                                             \\
          -SafeModeAdministratorPassword                                          \\
            (ConvertTo-SecureString 'Secret123' -AsPlainText -Force)
      register: installation
      args:
        creates: 'C:\\Windows\\NTDS'
    - win_reboot:
      when: installation.changed
    - win_service:
        name: adws
        start_mode: auto
        state: started
"""

ANSIBLE_AUTHENTICATIONTEST_AD_SERVER_ESTABLISH_TRUST_PLAYBOOK = """
---
- name: Setup DNS forwarder on AD DC
  hosts: windows
  tasks:
  - win_command: "dnscmd 127.0.0.1 /ZoneAdd ipa.test /Forwarder {ipa_server_ip}"

- name: Setup DNS forwarder on IPA server
  hosts: ipaserver
  become: true
  tasks:
  - ipadnsforwardzone:
      ipaadmin_password: password
      name: ad.test
      forwarders:
        - ip_address: {ad_server_ip}
      forwardpolicy: only
      state: present

- name: Add trust with AD domain
  hosts: ipaserver
  become: true
  tasks:
  - ipatrust:
      ipaadmin_password: password
      realm: ad.test
      admin: Administrator
      password: {windows_admin_password}
      state: present
"""

ANSIBLE_AUTHENTICATIONTEST_AD_SERVER_CREATE_USERS_PLAYBOOK = """
---
- name: Create AD users
  hosts: windows
  tasks:
  - win_shell: |
      Set-ADDefaultDomainPasswordPolicy ad.test -ComplexityEnabled $False
      for ($i = 0; $i -le {amount}; $i++) {{
        $num = $i.ToString("000")
        $name = "user{{0}}{{1}}" -f $num, "{client_hostname}"
        $password = ConvertTo-SecureString -AsPlainText 'password' -Force
        New-ADUser -SamAccountName $name -Name $name -AccountPassword $password -Enabled $True
      }}
"""

ANSIBLE_AUTHENTICATIONTEST_NOSELINUX_CONFIG_PLAYBOOK = """
---
- name: Disable SELinux in SSSD
  hosts: ipaclients
  tasks:
  - name: "Disable SELinux provider"
    become: yes
    lineinfile:
      path: /etc/sssd/sssd.conf
      line: selinux_provider = none
      insertafter: id_provider = ipa
"""
