| symbolList swordfishDictionary |
symbolList := System myUserProfile symbolList.
swordfishDictionary := symbolList objectNamed: #Swordfish.
swordfishDictionary ifNil: [
    Error signal: 'Swordfish package is not installed.'
].
(swordfishDictionary includesKey: #SwordfishMcpTracer)
    ifFalse: [
        Object
            subclass: #SwordfishMcpTracer
            instVarNames: #()
            classVars: #()
            classInstVars: #()
            poolDictionaries: #()
            inDictionary: swordfishDictionary
    ].
UserGlobals at: #SwordfishMcpTracerEnabled put: false.
true
