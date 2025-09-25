FOLDER_IDS = {
    "SOP › 5- Roles & Titles": "1JVuwFsOTjLX2DtiRKHM5mKzeXpj8pIYl",         #OK
    "SOP › Policies / ID": "to_configure",
    "SOP › 4- Employee Organization": "1GMDtaWtISRGC04L-C-gNA1peB2txkEzA",  #OK
    "HTPB Permits–Certificates": "1efN2fXFnI6MkA_AlAaY1eKOZLEJY5UWB",       #OK
    "KPIs / Finance": "to_configure",
    "Inventory / Reports": "to_configure",
    "Pricing / Images": "1DYQgdvzseGVUbmdNKiy6SdljFoly_Q5P"                 #OK
}


FALLBACK_DRIVES = [
    "1JgvFkJUrzuwhpggeOSrH1fgBhTjHYyBD",
    "17kUIyMg19PJ_E0Pewo9PZZeLw9z2pxPD"
]


prompt_map = {
        # === SOP › 5- Roles & Titles ===
        "bartender role description": {
            "query": "Bartender",
            "folder": "SOP › 5- Roles & Titles"
},
        "marketing / social media lead": {
            "query": "Marketing Social Media",
            "folder": "SOP › 5- Roles & Titles"
        },
        "bar manager sop": {
            "query": "Manager",
            "folder": "SOP › 5- Roles & Titles"
        },
        "show only word docs in roles & titles": {
    "query": "",  # vacío porque no quieres buscar texto
    "folder": "SOP › 5- Roles & Titles",
    "mime_filter": "mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
},


        # === SOP › Policies / ID ===
        "checking ids": {
            "query": "Checking IDs",
            "folder": "SOP › Policies / ID"
        },
        "proper forms of id accepted": {
            "query": "Proper Forms of ID Accepted",
            "folder": "SOP › Policies / ID"
        },
    "everything related to id-checking policy": {
    "query": "ID check OR wristband",
    "folder": "SOP › Policies / ID",   # 👈 Esto debe mapear a un ID en tu diccionario FOLDER_IDS
    "mode": "OR",
    "mime_filter": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/pdf",
        "image/jpeg",
        "image/png"
    ]
}
,



    # === SOP › 4- Employee Organization ===
        "employee organization chart": {
            "query": "Organization Chart",
            "folder": "SOP › 4- Employee Organization"
        },

        # === HTPB Permits–Certificates ===
        "abc liquor license": {
            "query": "ABC Liquor License",
            "folder": "HTPB Permits–Certificates"
        },
        "tennessee resellers certificate": {
            "query": "TN Resellers Certificate 1-31-25",
            "folder": "HTPB Permits–Certificates"
        },
        "ein letter": {
            "query": "EIN",
            "folder": "HTPB Permits–Certificates"
        },
        "metro liquor letter": {
            "query": "Metro Liquor letter in lieu",
            "folder": "HTPB Permits–Certificates"
        },
        "health permit": {
            "query": "Healthpermit",
            "folder": "HTPB Permits–Certificates"
        },
        "permits expiring soon": {
            "query": "*",
            "folder": "HTPB Permits–Certificates"
        },
        "large files in permits": {
    "query": "",
    "folder": "HTPB Permits–Certificates",
    "size_filter": ">5000000"

        },
        "permit numbers 23-28424 or 23-28425": {
    "query": "23-28424 OR 23-28425",
    "folder": "HTPB Permits–Certificates",  # 👈 aquí usas la carpeta correcta
    "mode": "OR"  # opcional, para dejar explícito el OR
},


        # === KPIs / Finance ===
        "key metrics to track": {
            "query": "Key Metrics to Track",
            "folder": "KPIs / Finance"
        },
        "bev-inco rating": {
            "query": "Bev-INCO",
            "folder": "KPIs / Finance"
        },
        "sale per check 22": {
    "query": ["Sale per check", "$22"],  # lista de términos
    "folder": "KPIs / Finance",
    "mode": "AND"
}
,

        "inventory turnover rate": {
            "query": "Inventory Turnover Rate",
            "folder": "KPIs / Finance"
        },

        # === Inventory / Reports ===
        "sculpture hospitality weekly report": {
    "query": "Sculpture Hospitality OR inteliPar",
    "folder": "Inventory / Reports"

        },
        "target stock on hand in weeks": {
            "query": "Target Stock on Hand in Weeks",
            "folder": "Inventory / Reports"
        },
    "three most recent inventory or stock reports": {
        "query": "Inventory OR Stock",
        "folder": "Inventory / Reports"
    },

    # === Pricing / Images ===
        "beverage price list": {
            "query": "Price List Beers Seltzers",
            "folder": "Pricing / Images"
        },

        # === Cross-folder ===
        "duplicates by title": {
            "query": "Duplicates",
            "folder": "All folders"
        }
    }