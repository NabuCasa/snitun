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

The session master creates a fernet token from client's config (aes/whitelist) and attaches the hostname and a utc timestamp with the lifetime validity of this token.

```json
{
  "valid": 1923841,
  "hostname": "myname.ui.nabu.casa",
  "aes_key": "hexstring",
  "aes_iv": "hexstring"
}
```

The SniTun server needs to be able to decrypt this token to validate the clients plausibility. SniTun after that, initializes a challenge response handling to validate the AES key and makes sure that it's the same client which made the requests for the fernet token from the session master.

SniTun server doesn't perform any user authentication!

### Challenge/Response

SniTun server creates a SHA256 from a random 40bit value. They will be encrypted and sent to the client. The client decrypts the value and performs again a SHA256 with this value and sends it encrypted back to SniTun. If the response is valid, the communication goes into Multiplexer mode.

## Multiplexer protocol

The header is encrypted with AES / CBC. The payload should be SSL encrypted!
The ID changes for every TCP connection and is unique for every connection. The SIZE is for the DATA payload.

EXTRA could be additional information like on NEW message it contains the caller IP address. Otherwise it's filled with random bits.

```
|________________________________________________________|
|-----------------HEADER---------------------------------|______________________________________________|
|------ID-----|--FLAG--|--SIZE--|---------EXTRA ---------|--------------------DATA----------------------|
|   16 bytes  | 1 byte | 4 bytes|       11 bytes         |                  variable                    |
|--------------------------------------------------------|----------------------------------------------|
```

Message Flags/Types:

- `0x01`: New | Extra data include first byte a ASCII value as `4` or `6` follow by the caller IP in bytes
- `0x02`: DATA
- `0x04`: Close
- `0x05`: Ping | Extra data are `ping` or `pong` as response of a ping.
