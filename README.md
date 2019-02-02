# SniTun
End-to-End encryption with SNI proxy on top of a TCP multiplexer

## Connection flow

```
                   [ CLIENT ] --AUTH/CONFIG--> [ SESSION MASTER ] (Trusted connection)
                   [ CLIENT ] <--FERNET-TOKEN- [ SESSION MASTER ]
                   [ CLIENT ] --------FERNET-TOKEN--------------------> [ SNITUN ] (Unsecure connection)
                   [ CLIENT ] <-------CHALLENGE-RESPONSE-(AES/CBC)----> [ SNITUN ]


             <--->                                                                  <------------------------------>
[ ENDPOINT ] <---> [ CLIENT ] <---------MULTIPLEXER---(AES/CBC)--------> [ SNITUN ] <------EXTERNAL-CONECTIONS-----> [ DEVICE ] (Trusted connection)
    |        <--->                                                                  <------------------------------>     |
    |                                                                                                                    |
    | <--------------------------------------------------END-TO-END-SSL------------------------------------------------->|
```

## Fernet token

The session master create a fernet token from client's config (aes/whitelist) and attach the hostname and a utc timestamp until this token is valid.

```json
{
    "valid": 1923841,
    "hostname": "myname.ui.nabu.casa",
    "aes_key": "hexstring",
    "aes_iv": "hexstring",
    "whitelist": []
}
```

The SniTun server need to be able to decrypt this token to validate the client plausibility. SniTun initialize after that a challenge response handling to validate the AES key and make sure that it's the same client as they requests the fernet token from session master.

SniTun server doesn't perform any user authentications!

### Challenge/Response

SniTun server create a SHA256 from a random 40bit value. They will be encrypted and send to client. This decrypt the value and perform again a SHA256 with this value and send it encrypted back to SniTun. If they is valid, he going into Multiplexer modus.

## Multiplexer protocol

The header is encrypted with AES / CBC. The Payload should be SSL!
The UUID change for every TCP connection and is single for every connection. The Size is for the DATA Payload.

```
|________________________________________________________|
|-----------------HEADER---------------------------------|______________________________________________|
|-----UUID----|--FLAG--|--SIZE--|---------RANDOM---------|--------------------DATA----------------------|
|   16 bytes  | 1 byte | 4 bytes|       11 bytes         |                  variable                    |
|--------------------------------------------------------|----------------------------------------------|
```

Message Flags/Types:
 - 0x01: New
 - 0x02: DATA
 - 0x04: Close
 - 0x05: Ping
