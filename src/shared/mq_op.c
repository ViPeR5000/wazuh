/* Copyright (C) 2009 Trend Micro Inc.
 * All rights reserved.
 *
 * This program is a free software; you can redistribute it
 * and/or modify it under the terms of the GNU General Public
 * License (version 2) as published by the FSF - Free Software
 * Foundation
 */

#include "shared.h"
#include "os_net/os_net.h"

#ifndef WIN32

/* Start the Message Queue. type: WRITE||READ */
int StartMQ(const char *path, short int type)
{
    if (type == READ) {
        return (OS_BindUnixDomain(path, SOCK_DGRAM, OS_MAXSTR + 512));
    }

    /* We give up to 21 seconds for the other end to start */
    else {
        int rc = 0;
        if (File_DateofChange(path) < 0) {
            sleep(1);
            if (File_DateofChange(path) < 0) {
                sleep(5);
                if (File_DateofChange(path) < 0) {
                    sleep(15);
                    if (File_DateofChange(path) < 0) {
                        merror(QUEUE_ERROR, path, "Queue not found");
                        return (-1);
                    }
                }
            }
        }

        /* Wait up to 3 seconds to connect to the unix domain.
         * After three errors, exit.
         */
        if ((rc = OS_ConnectUnixDomain(path, SOCK_DGRAM, OS_MAXSTR + 256)) < 0) {
            sleep(1);
            if ((rc = OS_ConnectUnixDomain(path, SOCK_DGRAM, OS_MAXSTR + 256)) < 0) {
                sleep(2);
                if ((rc = OS_ConnectUnixDomain(path, SOCK_DGRAM, OS_MAXSTR + 256)) < 0) {
                    merror(QUEUE_ERROR, path, strerror(errno));
                    return (-1);
                }
            }
        }

        mdebug1(MSG_SOCKET_SIZE, OS_getsocketsize(rc));
        return (rc);
    }
}

/* Send a message to the queue */
int SendMSG(int queue, const char *message, const char *locmsg, char loc)
{
    int __mq_rcode;
    char tmpstr[OS_MAXSTR + 1];

    tmpstr[OS_MAXSTR] = '\0';

    /* Check for global locks */
    os_wait();

    if (loc == SECURE_MQ) {
        loc = message[0];
        message++;

        if (message[0] != ':') {
            merror(FORMAT_ERROR);
            return (0);
        }
        message++; /* Pointing now to the location */

        if (strncmp(message, "keepalive", 9) == 0) {
            return (0);
        }

        snprintf(tmpstr, OS_MAXSTR, "%c:%s->%s", loc, locmsg, message);
    } else {
        snprintf(tmpstr, OS_MAXSTR, "%c:%s:%s", loc, locmsg, message);
    }

    /* Queue not available */
    if (queue < 0) {
        return (-1);
    }

    /* We attempt 5 times to send the message if
     * the receiver socket is busy.
     * After the first error, we wait 1 second.
     * After the second error, we wait more 3 seconds.
     * After the third error, we wait 5 seconds.
     * After the fourth error, we wait 10 seconds.
     * If we failed again, the message is not going
     * to be delivered and an error is sent back.
     */
    if ((__mq_rcode = OS_SendUnix(queue, tmpstr, 0)) < 0) {
        /* Error on the socket */
        if (__mq_rcode == OS_SOCKTERR) {
            merror("socketerr (not available).");
            close(queue);
            return (-1);
        }

        /* Unable to send. Socket busy */
        mwarn("Socket busy, waiting for 1 second.");
        sleep(1);
        if (OS_SendUnix(queue, tmpstr, 0) < 0) {
            /* When the socket is to busy, we may get some
             * error here. Just sleep 2 second and try
             * again.
             */
             mwarn("Socket busy, waiting for 3 seconds.");
             sleep(3);
            /* merror("socket busy"); */
            if (OS_SendUnix(queue, tmpstr, 0) < 0) {
              merror("Socket busy, waiting for 5 seconds.");
              sleep(5);
              if (OS_SendUnix(queue, tmpstr, 0) < 0) {
                    merror("socket busy, waiting for 10 seconds.");
                    sleep(10);
                    if (OS_SendUnix(queue, tmpstr, 0) < 0) {
                        /* Message is going to be lost
                         * if the application does not care
                         * about checking the error
                         */
                        close(queue);
                        return (-1);
                    }
                }
            }
        }
    }

    return (0);
}

/* Send a message to socket */
int SendMSGtoSCK(int queue, const char *message, const char *locmsg, char loc, logsocket **sockets)
{
    int __mq_rcode;
    char tmpstr[OS_MAXSTR + 1];
    int i = 0;

    while (sockets[i] && sockets[i]->name) {
        if (strcmp(sockets[i]->name, "agent") == 0) {
            SendMSG(queue, message, locmsg, loc);
        }
        else {
            tmpstr[OS_MAXSTR] = '\0';

            int sock_type;
            if (strcmp("udp",sockets[i]->mode) == 0) {
                sock_type = SOCK_DGRAM;
            } else if (strcmp("tcp",sockets[i]->mode) == 0) {
                sock_type = SOCK_STREAM;
            } else {
                merror("Socket type '%s' not valid.", sockets[i]->mode);
                return (-1);
            }

            // Check if the socket is connected
            if (sockets[i]->socket == 0) {
                // Try to connect to the socket
                if ((sockets[i]->socket = OS_ConnectUnixDomain(sockets[i]->location, sock_type, OS_MAXSTR + 256)) < 0) {
                    sleep(1);
                    if ((sockets[i]->socket = OS_ConnectUnixDomain(sockets[i]->location, sock_type, OS_MAXSTR + 256)) < 0) {
                        sleep(2);
                        if ((sockets[i]->socket = OS_ConnectUnixDomain(sockets[i]->location, sock_type, OS_MAXSTR + 256)) < 0) {
                            SendMSG(queue, "Socket not available.", locmsg, loc);
                            merror(QUEUE_ERROR, sockets[i]->location, strerror(errno));
                            return (-1);
                        }
                    }
                }
            }

            /* Queue not available */
            if (sockets[i]->socket == 0) {
                SendMSG(queue, "Socket not available.", locmsg, loc);
                merror(QUEUE_ERROR, sockets[i]->location, strerror(errno));
                return (-1);
            }

            // create message and add prefix
            if (sockets[i]->prefix && *sockets[i]->prefix) {
                snprintf(tmpstr, OS_MAXSTR, "%s:%s", sockets[i]->prefix, message);
            } else {
                snprintf(tmpstr, OS_MAXSTR, "%s", message);
            }

            mdebug2("Sending (%s) to socket '%s'",tmpstr,sockets[i]->name);
            if ((__mq_rcode = OS_SendUnix(sockets[i]->socket, tmpstr, 0)) < 0) {
                /* Error on the socket */
                if (__mq_rcode == OS_SOCKTERR) {
                    merror("Socket '%s' not available.", sockets[i]->name);
                    close(sockets[i]->socket);
                    return (-1);
                }
                /* Unable to send. Socket busy */
                mwarn("Socket busy, waiting for 1 second.");
                sleep(1);
                if (OS_SendUnix(sockets[i]->socket, tmpstr, 0) < 0) {
                    /* When the socket is to busy, we may get some
                     * error here. Just sleep 2 second and try
                     * again.
                     */
                     mwarn("Socket busy, waiting for 3 seconds.");
                     sleep(3);
                    /* merror("socket busy"); */
                    if (OS_SendUnix(sockets[i]->socket, tmpstr, 0) < 0) {
                      merror("Socket busy, waiting for 5 seconds.");
                      sleep(5);
                      if (OS_SendUnix(sockets[i]->socket, tmpstr, 0) < 0) {
                            merror("socket busy, waiting for 10 seconds.");
                            sleep(10);
                            if (OS_SendUnix(sockets[i]->socket, tmpstr, 0) < 0) {
                                SendMSG(queue, "Cannot send message to socket.", locmsg, loc);
                                close(sockets[i]->socket);
                                return (-1);
                            }
                        }
                    }
                }
            }
        }
        i++;
    }
    return (0);
}

#endif /* !WIN32 */
