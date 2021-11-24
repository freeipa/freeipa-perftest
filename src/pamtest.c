/*
* Copyright (C) 2021 FreeIPA Contributors see COPYING for license
*/

#define _GNU_SOURCE
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>
#include <security/pam_appl.h>
#include <security/pam_misc.h>
#include <pwd.h>
#include <sys/types.h>
#include <krb5.h>
#include <popt.h>
#include <sys/utsname.h>
#include <errno.h>
#include <string.h>

/* The only global, the name of the PAM service */
char * pam_service = NULL;

int *call_pam(void *ptr);

FILE *fp = NULL;

/*
 * Always return the fixed password string "password"
 */
int conv_static_password(int num_msg, const struct pam_message **msgm,
                         struct pam_response **response, void *appdata_ptr)
{
    struct pam_response *reply;

    reply = (struct pam_response *) calloc(num_msg,
					   sizeof(struct pam_response));
    if (reply == NULL) {
        fprintf(fp, "no memory for responses");
        return PAM_CONV_ERR;
    }
    char *string=NULL;

    string = strdup("password\0");
    reply[0].resp_retcode = 0;
    reply[0].resp = string;
    *response = reply;

    return PAM_SUCCESS;
}

static struct pam_conv conv = { conv_static_password, NULL };

int *call_pam(void *username)
{
    pam_handle_t *pamh;
    int result;

    fprintf(fp, "authenticating %s:%s\n", pam_service, (char *)username);
    if ((result = pam_start(pam_service, username, &conv, &pamh)) != PAM_SUCCESS) {
        fprintf(fp, "start for %s failed: %s (%d)\n", (char *)username, pam_strerror(pamh, result), result);
    } else if ((result = pam_authenticate(pamh, 0)) != PAM_SUCCESS) {
        fprintf(fp, "authenticate for %s failed: %s (%d)\n", (char *)username, pam_strerror(pamh, result), result);
    } else if ((result = pam_acct_mgmt(pamh, 0)) != PAM_SUCCESS) {
        fprintf(fp, "acct_mgmt for %s failed: %s (%d)\n", (char *)username, pam_strerror(pamh, result), result);
    } else { 
        fprintf(fp, "authenticated %s\n", (char *)username);

        if (geteuid() == 0) {
            /* When run as root we can verify that a ticket was obtained */
            const char *ccache_txt = NULL;
            char *outname = NULL;
            krb5_principal uprinc = NULL;
            krb5_context krbctx = NULL;
            krb5_ccache ccache = NULL;

            ccache_txt = pam_getenv(pamh, "KRB5CCNAME");
            setenv("KRB5CCNAME", ccache_txt, 1);
            fprintf(fp, "%s\n", ccache_txt);
            krb5_init_context(&krbctx);
            krb5_cc_default(krbctx, &ccache);
            krb5_cc_get_principal(krbctx, ccache, &uprinc);
            krb5_unparse_name(krbctx, uprinc, &outname);
            fprintf(fp, "principal %s\n", outname);
        }
    }

    if (pam_open_session(pamh, 0) != PAM_SUCCESS) {
        fprintf(fp, "open session for %s failed: %s (%d)\n", (char *)username, pam_strerror(pamh, result), result);
    } else {
        pam_close_session(pamh, 0);
    }
    if (pam_end(pamh, result) != PAM_SUCCESS) {
        fprintf(fp, "end failed:  %s (%d)\n", pam_strerror(pamh, result), result);
    }

    fprintf(fp, "Thread returned %i\n", result);
    return result;
}

int main(int argc, const char **argv)
{
    char *service = NULL;
    char *logfile = NULL;
    int threads = -1;
    pthread_t *ptr = NULL;
    int *index = NULL;
    char **usernames = NULL;
    int c, i;
    int ret = 0;
    struct utsname uinfo;
    poptContext pctx;
    struct poptOption popts[] = {
        {"outfile", 'o', POPT_ARG_STRING, NULL, 'o', NULL, "FILE"},
        {"service", 's', POPT_ARG_STRING, NULL, 's', NULL, "SERVICE"},
        {"threads", 't', POPT_ARG_INT, &threads, 0, NULL, NULL},
        POPT_AUTOHELP
        POPT_TABLEEND
    };

    pctx = poptGetContext("thread", argc, argv, popts, 0);
    if (pctx == NULL) {
        return -1;
    }
    while ((c = poptGetNextOpt(pctx)) > 0) {
        switch (c) {
        case 'o':
            logfile = poptGetOptArg(pctx);
            break;
        case 's':
            service = poptGetOptArg(pctx);
            break;
        }
    }
    if (c != -1) {
        poptPrintUsage(pctx, stdout, 0);
        ret = 1;
        goto done;
    } 

    if (threads == -1) {
        printf("--threads is required\n");
        poptPrintUsage(pctx, stdout, 0);
        ret = 1;
        goto done;
    }

    if (service == NULL) {
        pam_service = strdup("login");
    } else {
        pam_service = service;
    }

    if (logfile == NULL) {
        fp = stdout;
    } else {
        fp = fopen(logfile, "w");
        if (fp == NULL) {
            printf("Unable to open %s: %s\n", logfile, strerror(errno));
            ret = 1;
            goto done;
        }
    }

    uname(&uinfo);

    ptr = malloc(sizeof(pthread_t)*threads);
    if (ptr == NULL) {
        ret = 1;
        goto done;
    }
    index = calloc(threads, sizeof (int));
    if (index == NULL) {
        ret = 1;
        goto done;
    }

    usernames = calloc(threads, 256);
    if (usernames == NULL) {
        ret = 1;
        goto done;
    }

    for (i = 0; i < threads; i++) {
        asprintf(&usernames[i], "user%d%s", i, uinfo.nodename);
        index[i] = pthread_create(&ptr[i], NULL, call_pam, usernames[i]);
    }

    for (i = 0; i < threads; i++) {
        pthread_join(ptr[i], NULL);
    }

    for (i = 0; i < threads; i++) {
        free(usernames[i]);
    }

    free(usernames);
    free(index);
    free(ptr);

done:
    if (fp != NULL) {
        fclose(fp);
    }
    poptFreeContext(pctx);
    free(pam_service);
    free(logfile);
    return ret;
}
