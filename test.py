import middle.main

query = "in a restaurant can you use plastic cutting boards"

query = "Can a restaurant owner appeal a health inspection grade in NYC?"
print ("structuring query ...")
structured_question = middle.main.structure_question(query)
print ("finding matches ...")
matches = middle.main.get_values(structured_question)
print ("creating response ... ")
response = middle.main.structure_response(query, matches)

hold = 1