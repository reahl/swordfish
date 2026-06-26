*Acme-Amount-Core
readFromString: aString decimalFormat: decimalFormat
	^ aString ifEmpty: [ nil ] ifNotEmpty: [ :s | s asFloat ]