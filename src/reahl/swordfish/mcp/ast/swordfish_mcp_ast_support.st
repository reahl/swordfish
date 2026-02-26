| symbolList swordfishDictionary astClass |
symbolList := System myUserProfile symbolList.
swordfishDictionary := symbolList objectNamed: #Swordfish.
swordfishDictionary ifNil: [
    Error signal: 'Swordfish package is not installed.'
].
(swordfishDictionary includesKey: #SwordfishMcpAstSupport)
    ifFalse: [
        Object subclass: #SwordfishMcpAstSupport
            instVarNames: #()
            classVars: #()
            classInstVars: #()
            poolDictionaries: #()
            inDictionary: swordfishDictionary
    ].
astClass := swordfishDictionary at: #SwordfishMcpAstSupport.
astClass class
    compileMethod: 'argumentNamesForCompiledMethod: aCompiledMethod
    | argsAndTemps argumentCount names |
    argsAndTemps := aCompiledMethod argsAndTemps.
    argumentCount := aCompiledMethod numArgs.
    names := OrderedCollection new.
    1 to: argumentCount do: [ :index |
        names add: ((argsAndTemps at: index) asString)
    ].
    ^names asArray'
    dictionaries: symbolList
    category: 'swordfish-mcp-ast'
    environmentId: 0.
astClass class
    compileMethod: 'temporaryNamesForCompiledMethod: aCompiledMethod
    | argsAndTemps argumentCount names |
    argsAndTemps := aCompiledMethod argsAndTemps.
    argumentCount := aCompiledMethod numArgs.
    names := OrderedCollection new.
    (argumentCount + 1) to: argsAndTemps size do: [ :index |
        names add: ((argsAndTemps at: index) asString)
    ].
    ^names asArray'
    dictionaries: symbolList
    category: 'swordfish-mcp-ast'
    environmentId: 0.
astClass class
    compileMethod: 'supportsSwordfishMcpAst
    ^true'
    dictionaries: symbolList
    category: 'swordfish-mcp-ast'
    environmentId: 0.
true
