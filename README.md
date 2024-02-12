# FreeIPA Performance Testing

Collection of performance and scalability-related testing scripts.

## Dependencies

This tool can use these providers to deploy VMs for testing:

* Vagrant
* IdM CI (uses Red Hat's internal infrastructure, needs authentication)

The controller must have the following software installed:

* `ansible`
* `git`
* `rsync`

For using the Vagrant provider, these need to be installed as well:

* `vagrant`
* `libvirt`
* Vagrant plugins
   * `vagrant-libvirt`
   * `winrm` (for AD support)
   * `winrm-elevated` (for AD support)

## Usage

```
Usage: ipaperftest [OPTIONS]

Options:
  --test [EnrollmentTest|APITest|AuthenticationTest|GroupSizeTest]
                                  Test to execute.  [default: EnrollmentTest]
  --client-image TEXT             Image to use for clients.
  --server-image TEXT             Image to use for server.
  --amount INTEGER                Size of the test.  [default: 1]
  --replicas INTEGER RANGE        Number of replicas to create.  [default: 0;
                                  0<=x<=64]
  --threads INTEGER               Threads to run per client during
                                  AuthenticationTest.  [default: 10]
  --ad-threads INTEGER            Active Directory login threads to run per
                                  client during AuthenticationTest.  [default:
                                  0]
  --sizelimit INTEGER             IPA search size limit  [default: 100]
  --disable-selinux               Disable the SSSD SELinux provider in all
                                  clients, enable forking in pamtest
  --command TEXT                  Command to execute during APITest.
  --results-format [json|human]   Format to use for results output  [default:
                                  json]
  --results-output-file TEXT      File to write results output to
  --custom-repo-url TEXT          URL from custom repo to be configured on the
                                  server hosts. Make sure N-V-R is higher than
                                  the packages available in the server image
                                  so that your packages are used.
  --provider [vagrant|idmci]      Provider to use during test execution
                                  [default: idmci]
  --private-key TEXT              Private key needed to access VMs in case the
                                  default is not enough.
  --sequential                    Run APITest commands sequentially from a
                                  single client.
  --idmci-lifetime INTEGER        Lifetime in hours of IdM-CI hosts.
                                  [default: 8]
  --auth-spread INTEGER           Time range in minutes to spread auths in
                                  AuthenticationTest  [default: 0]
  --expected-result-type [time|time_unit|no_errors]
                                  Type of expected result.  [default:
                                  no_errors]
  --expected-result FLOAT         Expected result of the test, in seconds.
  --number-of-subgroups INTEGER   Number of sub groups for Groupsize test
                                  [default: 0]
  --help                          Show this message and exit.
```

## Capturing results

After executing the script, a `sync` directory will be created. There you will find logs gathered from all the machines
deployed, including performance monitoring using SAR.

A tarball will be created containing the sync directory and metadata like Ansible playbooks and Vagrantfile.

## Expecting results

A result can be passed to the tool so that it fails if the actual
result is longer than expected. The currently supported types of expected
results are:

* `time`: total time of execution of the test, excluding setup.
* `time_unit`: time of execution per each item (defined by `amount`), excluding setup.
* `no_errors`: the test will succeed as long as no errors are raised.

## Development

The package can be tested and developed in a python virtual environment.

To create the virtual environment run:

```
$ python3 -m venv --system-site-packages venv
$ venv/bin/pip install -e .
```

To use the environment:

```
$ source venv/bin/activate
```

If you are using the IdM CI provider, the Ansible Vault password file needs to be set up:

```
$ echo 'IDMCI_VAULT_PASSWORD' > ~/.idmci-ansible-vault-password-file
```

To run the tool:

```
$ source venv/bin/activate
$ ipaperftest
```

## Sample usage

To run an enrollment test, with 100 clients and 2 replicas:

```
$ ipaperftest --test EnrollmentTest --replicas 2 --amount 100
```

## Available tests

### EnrollmentTest

Try to enroll n clients simultaneously, n being the amount especified using the `amount` option.
During this test, n client machines are created and configurated.
After this, they are all scheduled to launch `ipa-client-install` at the same time. A wait is added to ensure
all machines are properly configured before the client installation time. Once all the install processes exit,
the results are retrieved. To ensure that enrollment went well on both ends, clients successes are counted and
compared against the output of `ipa host-find` on the server.

If using replicas, the distribution of enrollments between servers will be shown after the test.

### AuthenticationTest

Perform authentication attempts against the server. The number of clients deployed is set using the `amount` option,
and the amount of authentication threads per client is defined using the `threads` option, so the total amount of
authentication attemps performed is `amount` * `threads`.

Before launching the authentications both server and clients are configured. Test users are created using the
`create-test-data.py` and `set-password.py` scripts, as explained below. After this, authentications are attempted
using the `pamtest` tool. A file named `pamtest.log` will be created for each client, containing logs from this run.

After the test execution, percentage of succeeded attempts will be shown, both per client and in total.

### APITest

This tests runs the same command n times simultaneously. The command is specified using the `command` option. The
wildcard `{id}` is permitted for commands that required variability to run properly (for example, it can be used
as a username so that the `user-add` command can be run multiple times without failing). The amount of commands to
run is set using the `amount` options, and these commands will be run from clients deployed before the test. Each
client deployed will run a maximum of 25 commands. These commands are scheduled on the client using the `at` tool.

There is an option to run the test in sequential mode. When this mode is activated, only one client will be deployed,
and commands will be executed sequentially from this single client.

After the execution of the test, output from the commands will be written to the `sync` directory.

### GroupSizeTest

Determine how long it takes to add one more user to a group. As groups grow in size the LDAP
memberof and indexing calculations becomes more intense. This test creates a selected number
of users as an LDIF, as members of a new group (allusers). It then calls ipa group-add-member to add
one more user and returns the wall-clock time to do so. In IPA generally we try to keep
times under 2s.

There is also the capability to create subgroups. Long ago subgroups was proposed as a
workaround to a single group with a large number of members. The number of subgroups
is specified iwth --number-of-subgroups. These are all members of a new top-level group
and users are more or less equally assigned to the subgroups. Then one more member is
added to a subgroup and the time returned.

#### Options
Rather than declaring a bunch of new options some are reused. The available options
are:

- `threads`: number of users to create
- `number-of-subgroups`: number of subgroups to create (if not specified there is a single group)

Sample execution:

```
ipaperftest --test GroupSizeTest --threads 1500
ipaperftest --test GroupSizeTest --threads 1500 --number-of-subgroups 3 
```

### CertIssuanceTest

Find the limit of the IPA API to issue new certificates.

A set number of clients is enrolled then services for each client are created.

For each service an ipa-getcert request is issued. There is little effort made
to ensure that these are all run at the same time but in the end this more
closely mirrors a live installation.

#### Options
Rather than declaring a bunch of new options some are reused. The available options
are:

- `cert-requests`: number of certificates to request for each client
- `clients`: number of clients to enroll
- `wsgi-processes`: number of WSGI processes to enable (default=4)

Sample execution:

```
ipaperftest --test CertIssuanceTest --amount 70  --cert-requests 5
ipaperftest --test CertIssuanceTest --amount 70  --cert-requests 5 --wsgi-processes 8
```

## Creating test users

For client authentication test we need a lot of users to test against.
The combination of two scripts will create the users needed for testing
with identical, unexpired passwords.

In order to set passwords using a pre-hashed password IPA needs to
be in migration mode:

```
$ kinit admin
$ ipa config-mod --enable-migration=true
```

Create 10 users for each of 500 hosts. The format of the uid is
user#client@.<domain>.

```
$ ./create-test-data.py  > user.ldif
$ ldapadd -x -D 'cn=directory manager' -W < user.ldif
```

Time to add depends on the server but for me it was ~9 minutes.

Now reset all Kerberos credentials to the value of 'password':

```
./set-password.py --dm-password <Directory Manager password>
```

Time to reset the passwords is ~11 minutes. This is done as the
DM user requesting a keytab for each user which will set the
Kerberos credentails. The LDAP password is set on the import.
