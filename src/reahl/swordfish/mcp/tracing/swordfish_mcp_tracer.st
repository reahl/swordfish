(UserGlobals includesKey: #SwordfishMcpTracer)
    ifFalse: [
        Object
            subclass: #SwordfishMcpTracer
            instVarNames: #()
            classVars: #()
            classInstVars: #()
            poolDictionaries: #()
            inDictionary: UserGlobals
    ].
UserGlobals at: #SwordfishMcpTracerEnabled put: false.
true
