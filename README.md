# FreeIPA Performance Testing

Collection of performance and scalability-related testing scripts.

## Dependencies

This tool uses Vagrant and Libvirt to deploy VMs for testing.
The controller must have the following software installed:

* `vagrant`
* `ansible`
* `libvirt`
* `vagrant-libvirt` (vagrant plugin)
* `git`
* `rsync`

## Usage

`./ipaperftest.py [OPTIONS]`

* `test`: Test to perform. Current options are:
  * `EnrollmentTest`: Try to enroll n clients simultaneously. This is the default.
  * `APITest`: Try to run IPA command n times simultaneously.
* `amount`: Size of the test. For example, in the case of `EnrollmentTest`, it will create this amount of clients. 
* `command`: Command to run. Only relevant when using `APITest`. Use `{id}` for getting an unique ID into the command. Example: `ipa user-add user{id}`.
* `client-image`: Vagrant image to use for the clients. Default: `antorres/fedora-34-ipa-client`. If you use a different image, make sure it has all the needed packages installed:
    * `freeipa-client`
    * `at` (make sure to enable `atd` service too)
* `server-image`: Vagrant image to use for the server. Default: `antorres/fedora-34-ipa-client`.
* `private_key`: Path to an additional private key in case your image needs it to access via SSH.

## Capturing results

After executing the script, a `sync` directory will be created. There you will find logs gathered from all the machines deployed, including performance monitoring using SAR.
