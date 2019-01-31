# snitun
End-to-End encryption with SNI proxy on top of a TCP multiplexer

## Connection

```
[ CLIENT ] --AUTH/CONFIG--> [ SESSION MASTER ] (Trusted connection)
[ CLIENT ] <--FERNET-TOKEN- [ SESSION MASTER ]
[ CLIENT ] ---------FERNET-TOKEN------------------------> [ SNITUN ] (Unsecure connection)
[ CLIENT ] <--------CHALLENGE-RESPONSE-(AES/CBC)--------> [ SNITUN ] (Unsecure connection)


[ CLIENT ] <-------------MULTIPLEXER---(AES/CBC)--------> [ SNITUN ] <----------EXTERNAL-CONECTION--------> [ DEVICE ]
    | <-----------------------------------------------END-TO-END-SSL------------------------------------------->|
```


## Multiplexer

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
