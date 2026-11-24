
import json
import ollama
import config
from models import normalize_request


# default search values if not specified

DEFAULT_REQUEST = {
    "dessert_type": None,
    "flavor": None,
    "max_price": 10.0,
    "location": "Cookeville, TN",
    "max_distance_miles": None
}


# system prompt
SYSTEM_PROMPT = """
You are Sweetery's Natural Language Processing agent.

Your task is to interpret the user's dessert search query
and convert it into structured search parameters.

You must always interpret the query and return a structured request.
Never ask follow-up questions.

EXTRACT THESE FIELDS:

- dessert_type
- flavor
- max_price
- location
- max_distance_miles

DEFAULT VALUES:

If the user does not specify a value, use these defaults:

- dessert_type: null
- flavor: null
- max_price: 10.0
- location: "Cookeville, TN"
- max_distance_miles: null

INTERPRETATION RULES:

1. Extract only preferences and restrictions that the user expresses.

2. Do not invent preferences.

3. If the user does not specify a dessert type,
   return null for dessert_type.
   This means the user is open to any dessert.

4. If the user does not specify a flavor,
   return null for flavor.
   This means the user is open to any flavor.

5. If the user specifies a flavor but not a dessert type,
   search across all dessert types matching that flavor.

6. If the user specifies a price limit,
   return the maximum price as a number.

7. If the user does not specify a price limit,
   use 10.0.

8. If the user does not specify a location,
    use "Cookeville, TN".

9. If the user specifies a maximum distance,
    return that distance in miles as a number.

10. If the user does not specify a distance,
    return null for max_distance_miles.
    This means there is no distance restriction.

11. Convert distances to miles when other units are used.

12. Convert prices to numeric values.
    For example, "$8" should be 8.0.

13. Correct obvious spelling mistakes.

DESSERT TYPE RULES:

Recognize desserts and common synonyms, including:

- cupcakes
- cakes
- cookies
- brownies
- donuts / doughnuts
- ice cream
- cheesecake
- pies
- pastries
- pudding

Return a normalized dessert name when possible.

FLAVOR RULES:

1. Return only one flavor.

2. The flavor must be one of the following:
   chocolate, vanilla, strawberry, blueberry, lemon,
   ginger, molasses, apple.

3. Normalize synonyms, descriptive words, and spelling variations
   to one of the supported flavors.
   
4. Correct obvious spelling mistakes.

5. Do not infer a specific flavor from vague terms such as
   "sweet", "fruity", or "refreshing".

6. If a flavor is not specified, return null.

7. Do not invent flavors.

8. If no supported flavor is explicitly specified, return null.

9. Never return a flavor outside the supported list.

DISTANCE RULES:

1. Extract the maximum distance only if the user specifies it.

2. Convert feet, yards, or kilometers into miles.

EXAMPLES:

User: "Chocolate desserts"

{
    "dessert_type": null,
    "flavor": "chocolate",
    "max_price": 10.0,
    "location": "Cookeville, TN",
    "max_distance_miles": null,
}

User: "Chocolate cupcakes"

{
    "dessert_type": "cupcake",
    "flavor": "chocolate",
    "max_price": 10.0,
    "location": "Cookeville, TN",
    "max_distance_miles": null,
}

User: "Cheesecake under $5"

{
    "dessert_type": "cheesecake",
    "flavor": null,
    "max_price": 5.0,
    "location": "Cookeville, TN",
    "max_distance_miles": null,
}

User: "Brownies within 5 miles"

{
    "dessert_type": "brownie",
    "flavor": null,
    "max_price": 10.0,
    "location": "Cookeville, TN",
    "max_distance_miles": 5.0,
}

User: "Any dessert under $15"

{
    "dessert_type": null,
    "flavor": null,
    "max_price": 15.0,
    "location": "Cookeville, TN",
    "max_distance_miles": null,
}

User: "Chocolate desserts in Cookeville with no price limit"

{
    "dessert_type": null,
    "flavor": "chocolate",
    "max_price": null,
    "location": "Cookeville, TN",
    "max_distance_miles": null,
}


CONVERSATION RULES:

- Treat every query as a new independent search.
- Do not preserve criteria from previous searches.
- Return a structured request for every query.
- Never ask follow-up questions.
- Only return one flavor.
"""


# response schema
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "request": {
            "type": "object",
            "properties": {
                "dessert_type": {
                    "type": ["string", "null"]
                },
                "flavor": {
                    "type": ["string", "null"]
                },
                "max_price": {
                    "type": ["number", "null"]
                },
                "location": {
                    "type": ["string", "null"]
                },
                "max_distance_miles": {
                    "type": ["number", "null"]
                }
            },
            "required": [
                "dessert_type",
                "flavor",
                "max_price",
                "location",
                "max_distance_miles"
            ],
            "additionalProperties": False
        }
    },
    "required": ["request"],
    "additionalProperties": False
}


# apply default values if needed
def apply_defaults(request):

    final_request = DEFAULT_REQUEST.copy()

    for key in DEFAULT_REQUEST:
        value = request.get(key)

        if value is not None:
            final_request[key] = value

    return final_request


# structuring the requests
def understand_query(user_query):

    model = config.OLLAMA_MODEL or "llama3.2"

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": user_query
        }
    ]

    try:
        response = ollama.chat(
            model=model,
            messages=messages,
            format=RESPONSE_SCHEMA,
            options={"temperature": 0}
        )

        data = json.loads(response.message.content)

        request = data.get("request", {})


        # apply defaults
        request = apply_defaults(request)

        # normalize using the existing model utility
        request = normalize_request(request)

        # ensure defaults are retained after normalization
        request = apply_defaults(request)
        # validate flavor against supported choices
        flavor = request.get("flavor")

        if isinstance(flavor, str):
            flavor = flavor.strip().lower()

        if flavor not in config.FLAVOR_CHOICES:
            request["flavor"] = None
        else:
            request["flavor"] = flavor
        return {
            "request": request
        }

    except Exception as e:
        print(f"Natural Language Agent Error: {e}")

        # return default criteria if the LLM fails
        return {
            "request": DEFAULT_REQUEST.copy()
        }
