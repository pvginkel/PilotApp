"""What passes between a collector and Pilot (F152.1 to F152.3, F152.6,
F152.11, F152.13, F158.5): the shape of a publication,
`pilot_collection.publication`, of Pilot's inventory,
`pilot_collection.inventory`, of the labeller's vocabularies,
`pilot_collection.vocabularies`, of the Repositories and a read of one,
`pilot_collection.repositories`, of the Files and their classes,
`pilot_collection.files`, and of a conversation's reading,
`pilot_collection.reading`. It imports nothing of the database,
Flask or the app, so that a collector takes the shapes Pilot's routes
validate against, and Pilot the shape a collector serves."""
