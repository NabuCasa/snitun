# SniTun

End-to-End encryption with SNI proxy on top of a TCP multiplexer

## Connection flow

```
                   [ CLIENT ] --AUTH/CONFIG--> [ SESSION MASTER ] (Trusted connection)
                   [ CLIENT ] <--FERNET-TOKEN- [ SESSION MASTER ]
                   [ CLIENT ] --------FERNET-TOKEN---------------------> [ SNITUN ] (Unsecure connection)
                   [ CLIENT ] <-------CHALLENGE-RESPONSE-(AES/CBC)-----> [ SNITUN ]


             <--->                                                                  <------------------------------>
[ ENDPOINT ] <---> [ CLIENT ] <---------MULTIPLEXER---(AES/CBC)--------> [ SNITUN ] <------EXTERNAL-CONECTIONS-----> [ DEVICE ]
    |        <--->                                                                  <------------------------------>     |
    |                                                                                                                    |
    | <--------------------------------------------------END-TO-END-SSL------------------------------------------------->|
                                                      (Trusted connection)
```

## Fernet token

The session master creates a Fernet token from the client's configuration (AES/whitelist) and attaches the hostname and a UTC timestamp until which the token is valid.

```json
{
"valid": 1923841,
"hostname": "myname.ui.nabu.casa",
"aes_key": "hexstring",
"aes_iv": "hexstring"
}
```

The SniTun server must be able to decrypt this token to validate the client's authenticity. SniTun then initiates a challenge-response handling to validate the AES key and ensure that it is the same client that requested the Fernet token from the session master.

Note: SniTun server does not perform any user authentication!

### Challenge/Response:
The SniTun server creates a SHA256 hash from a random 40-bit value. This value is encrypted and sent to the client, who then decrypts the value and performs another SHA256 hash with the value and sends it encrypted back to SniTun. If it is valid, the client enters the Multiplexer mode.

## Multiplexer Protocol:
The header is encrypted using AES/CBC. The payload should be SSL. The ID changes for every TCP connection and is unique for each connection. The size is for the data payload.

The extra information could include the caller IP address for a new message. Otherwise, it is random bits.


```
|________________________________________________________|
|-----------------HEADER---------------------------------|______________________________________________|
|------ID-----|--FLAG--|--SIZE--|---------EXTRA ---------|--------------------DATA----------------------|
|   16 bytes  | 1 byte | 4 bytes|       11 bytes         |                  variable                    |
|--------------------------------------------------------|----------------------------------------------|
```

Message Flags/Types:

- `0x01`: New | The extra data includes the first byte as an ASCII value of 4 or 6, followed by the caller IP in bytes.
- `0x02`: DATA
- `0x04`: Close
- `0x05`: Ping | The extra data is a `ping` or `pong` response to a ping.
