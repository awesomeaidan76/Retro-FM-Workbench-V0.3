# Full legacy parser plugin contract

The workbench cannot safely invent the binary schema of proprietary legacy `.dat` files. A version-specific parser is therefore loaded as a plugin.

Invocation:

```text
parser --input <legacy file or folder> --output <output folder>
```

For `.py` plugins, the workbench invokes the current Python interpreter.

Required output (either or both):

```text
people.json
people.csv
```

Accepted normalized fields include:

```text
name,first_name,last_name,date_of_birth,nationality,second_nationality,club,
position,role,ca,pa,reputation,contract_expiry,wage,
pace,acceleration,agility,balance,jumping,natural_fitness,stamina,strength,
finishing,first_touch,heading,passing,technique,dribbling,tackling,marking,
anticipation,composure,concentration,decisions,determination,flair,leadership,
off_the_ball,positioning,teamwork,vision,work_rate,crossing,long_shots,
penalties,free_kicks,corners,throw_ins,handling,reflexes,one_on_ones,
aerial_reach,command_of_area,eccentricity,communication,kicking,influence,
bravery,aggression,creativity,left_foot,right_foot,versatility,db_unique_id
```

The parser may output more fields. Unknown fields are kept during ingestion but may be mapped to `(ignore)` automatically.

A parser does not have to create FM24/FM26 XML. It only needs to produce structured historical records. The workbench performs the target mapping and validation, and FMME can perform version-specific XML generation.
