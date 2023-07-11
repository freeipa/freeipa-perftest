#!/bin/bash
#
# Generate a lot of certificates for the same service
#
# $1 service name
# $2 number of certificates
#
# General timeframes for issuance (wall clock):
# 1000 certificates 22 min
# 2000 certificates 43 min
# 3000 certificates 65 min
# 4000 certificates 90 min

if [ $# -ne 2 ]; then
    echo "Usage: $0 service_name quantity"
    exit 1
fi

name=$1
quantity=$2

CERTPATH=/etc/pki/tls/certs/test.pem
KEYPATH=/etc/pki/tls/private/test.key
FQDN=$(hostname -f)

kinit -kt /etc/krb5.keytab > /dev/null 2>&1
ipa service-add ${name}/${FQDN} > /dev/null 2>&1

for (( i=1; i<=$quantity; i++ )); do
    echo "Getting cert $i"
    ipa-getcert request -f $CERTPATH -k $KEYPATH -K ${name}/${FQDN}-v -w > /dev/null 2>&1
    getcert stop-tracking -f $CERTPATH > /dev/null 2>&1
    ipa service-mod --certificate='' ${name}/${FQDN} > /dev/null 2>&1
    rm -f $CERTPATH
done
