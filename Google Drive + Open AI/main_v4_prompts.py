# ------------------ IMPORTS ------------------
import os
from io import BytesIO
import pandas as pd
from googleapiclient.http import MediaIoBaseDownload
from rapidfuzz import process
import const.constants as c
import re
from helpers.analyzer import get_credentials, download_file_as_dataframe, ask_llm_about_dataframe, compare_two_dataframes
from googleapiclient.discovery import build
from rapidfuzz import fuzz, distance

# Libraries for Google OAuth authentication
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

def validate_folders():
    print("\n[VALIDATING PROMPT MAP FOLDERS]")
    for key, entry in c.prompt_map.items():
        folder_name = entry["folder"]
        folder_id = c.FOLDER_IDS.get(folder_name)
        if not folder_id:
            print(f"⚠️  Prompt '{key}' points to folder '{folder_name}' which is NOT in FOLDER_IDS")
        elif folder_id == "to_configure":
            print(f"⚠️  Prompt '{key}' points to folder '{folder_name}' but is set as 'to_configure'")
        else:
            print(f"✅ Prompt '{key}' correctly linked to folder '{folder_name}' ({folder_id})")

# validate_folders()

# ------------------ CONFIG ------------------
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']



# ------------------ AUTHENTICATION ------------------
def get_credentials():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds


creds = get_credentials()
drive_service = build('drive', 'v3', credentials=creds)


# ------------------ EXTRACT SNIPPETS ------------------
def extract_snippet(file_bytes, mime_type, query):
    try:
        if mime_type == "text/csv":
            df = pd.read_csv(file_bytes, dtype=str, encoding="utf-8", errors="ignore")
        else:
            df = pd.read_excel(file_bytes, dtype=str, engine="openpyxl")

        df = df.dropna(axis=1, how="all")
        df = df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed")]

        mask = df.apply(lambda row: row.astype(str).str.contains(query, case=False, na=False).any(), axis=1)
        matches = df[mask]

        if not matches.empty:
            fragment = matches.head(2).to_string(index=False)
            return fragment[:300]
        else:
            return "⚠️ No match found in file content."
    except Exception as e:
        return f"⚠️ Error reading file: {e}"


# ------------------ LIST FILES (RECURSIVE) ------------------
def list_files_recursive(folder_id):
    all_files = []
    page_token = None

    while True:
        results = drive_service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, parents)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageToken=page_token
        ).execute()

        items = results.get('files', [])
        for item in items:
            if item["mimeType"] == "application/vnd.google-apps.folder":
                all_files.extend(list_files_recursive(item["id"]))
            else:
                all_files.append(item)

        page_token = results.get('nextPageToken', None)
        if page_token is None:
            break

    return all_files


# ------------------ SEARCH ------------------
def search_drive(query, folder_id=None, mime_filters=None, mode="AND", options=None):
    """
    Search for files in Google Drive with multiple keyword support.
- United States AND by default.
- If the query contains an explicit 'OR' → switches to OR.
- If query is a list → terms and mode (AND/OR) are respected.
- If folder_id is None → searches the entire Drive (and applies a MIME post-filter).
- mime_filters can be:
- None
- str (e.g., "mimeType='application/pdf'")
- list (e.g., ["application/pdf", "image/png"])
    """

    results = []
    page_token = None

    # --- 1. detect joiner y keywords ---
    if isinstance(query, list):
        raw_keywords = query
        joiner = " and " if mode.upper() == "AND" else " or "
    elif " OR " in query:
        raw_keywords = [w.strip() for w in query.split("OR") if w.strip()]
        joiner = " or "
    else:
        raw_keywords = [w.strip() for w in query.replace("/", " ").split() if len(w.strip()) > 2]
        joiner = " or " if mode.upper() == "OR" else " and "

    # --- 2. construct conditions ---
    if raw_keywords:
        name_conditions = joiner.join([f"name contains '{k}'" for k in raw_keywords])
        text_conditions = joiner.join([f"fullText contains '{k}'" for k in raw_keywords])
    else:
        name_conditions = f"name contains '{query}'"
        text_conditions = f"fullText contains '{query}'"

    # --- 3. folder filter ---
    folder_filter = f" and '{folder_id}' in parents" if folder_id else ""

    # --- 4. Filtro de MIME ---
    if mime_filters:
        if isinstance(mime_filters, list):
            mime_filter_str = "(" + " or ".join([f"mimeType='{m}'" for m in mime_filters]) + ") and "
        else:
            mime_filter_str = f"{mime_filters} and "
    else:
        mime_filter_str = ""

    # --- 5. Query final ---
    q = f"{mime_filter_str}trashed=false and (({name_conditions}) or ({text_conditions})){folder_filter}"

    # ✅ Si hay fechas detectadas, añadirlas como condiciones extra
    if options and "dates" in options:
        for d in options["dates"]:
            q += f" and (name contains '{d}' or fullText contains '{d}')"

    print("[DEBUG] Final query sent to Drive:", q)

    # --- 6. Execute by page ---
    while True:
        response = drive_service.files().list(
            q=q,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageToken=page_token
        ).execute()

        results.extend(response.get("files", []))
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break

    # --- 7. Filter only if is global ---
    if folder_id is None:
        ALLOWED_MIME_TYPES = {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
            "application/pdf",
            "text/plain",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.ms-powerpoint",
        }
        results = [f for f in results if f["mimeType"] in ALLOWED_MIME_TYPES]

    return results




#--------------------RANK RESULTS------------------------



def rank_results(results, query):
    ranked = []

    if isinstance(query, list):
        q = " ".join(query).lower()
    else:
        q = str(query).lower()

    query_tokens = q.split()

    for f in results:
        title = f.get("name", "").lower()

        # fuzzy base
        score_partial = fuzz.partial_ratio(q, title)
        score_token = fuzz.token_sort_ratio(q, title)
        score = (0.7 * score_partial) + (0.3 * score_token)

        # complete sentence
        phrase_score = fuzz.ratio(q, title)
        score = max(score, phrase_score)

        # typo token-level
        for token in query_tokens:
            for word in title.split():
                dist = distance.Levenshtein.distance(token, word)
                if dist == 1:  # un carácter diferente (ej. manger vs manager)
                    score += 15
                elif dist == 2 and len(token) > 5:  # errores de 2 letras en palabras largas
                    score += 7

        ranked.append((score, f))

    ranked.sort(key=lambda x: (x[0], x[1].get("modifiedTime", "")), reverse=True)
    return ranked




# ------------------ PROMPT INTERPRETER ------------------
STOPWORDS = {"list", "show", "open", "the", "a", "an", "of", "in", "on", "to", "for"}

def normalize_prompt(text):
    # quita puntuación
    text = re.sub(r"[^a-zA-Z0-9\s]", "", text)
    # minúsculas
    words = text.lower().split()
    # quita stopwords
    words = [w for w in words if w not in STOPWORDS]
    return " ".join(words)

def parse_size_from_prompt(user_prompt: str):
    """
    Detect specific size
    """
    match = re.search(r'(\d+)\s*mb', user_prompt.lower())
    if match:
        size_mb = int(match.group(1))
        return size_mb * 1024 * 1024
    return None


def group_near_duplicates(files, threshold=85):
    groups = []
    used = set()

    for i, f1 in enumerate(files):
        if f1["id"] in used:
            continue
        group = [f1]
        for j, f2 in enumerate(files[i+1:], start=i+1):
            score = fuzz.token_sort_ratio(f1["name"].lower(), f2["name"].lower())
            if score >= threshold:
                group.append(f2)
                used.add(f2["id"])
        if len(group) > 1:  # solo mostrar grupos con duplicados
            groups.append(group)
            for f in group:
                used.add(f["id"])
    return groups



def interpret_prompt(user_prompt):
    normalized_prompt = normalize_prompt(user_prompt)

    import re
    # detect permissions
    permit_match = re.compile(r"\b\d{2}-\d{5}\b")
    numbers = permit_match.findall(user_prompt)

    if numbers:
        print(f"[DEBUG] Dynamic permit search detected → {numbers}")
        query = " OR ".join(numbers)
        folder = c.FOLDER_IDS.get("HTPB Permits–Certificates", None)
        mime_filter = None
        options = {}
        mode = "OR"
        return query, folder, mime_filter, options, mode

    # --- detect size (ej. 5 MB, 1GB) ---
    size_match = re.findall(r"(\d+(?:\.\d+)?)\s*(MB|GB|KB)", user_prompt, re.IGNORECASE)

    dynamic_size = None
    if size_match:
        num, unit = size_match[0]
        num = float(num)  # 👈 ahora soporta decimales
        unit = unit.upper()
        if unit == "KB":
            dynamic_size = int(num * 1024)
        elif unit == "MB":
            dynamic_size = int(num * 1024 * 1024)
        elif unit == "GB":
            dynamic_size = int(num * 1024 * 1024 * 1024)
        print(f"[DEBUG] Size detected → {num} {unit} = {dynamic_size} bytes")

    # --- detect '$' ---
    money_match = re.findall(r"\$\d+(?:\.\d+)?", user_prompt)

    # --- mapping prompt_map ---
    normalized_keys = {k: normalize_prompt(k) for k in c.prompt_map.keys()}

    best_match, score, _ = process.extractOne(
        normalized_prompt,
        list(normalized_keys.values()),
        score_cutoff=65
    )

    if best_match and score >= 65:
        original_key = [k for k, v in normalized_keys.items() if v == best_match][0]
        entry = c.prompt_map[original_key]
        query = entry["query"]   # puede ser str o list

        # if amount → add it
        if money_match:
            if isinstance(query, list):
                query = query + money_match
            else:
                query = [query] + money_match
            print(f"[DEBUG] Monetary value(s) detected → {money_match}")

        folder = None if entry["folder"] == "All folders" else c.FOLDER_IDS.get(entry["folder"], None)
        if folder == "to_configure":
            folder = None

        mime_filter = entry.get("mime_filter", None)
        mode = entry.get("mode", "AND")
    else:
        query = user_prompt
        folder = None
        mime_filter = None
        mode = "AND"

    # ---  extras ---
    options = {}

    # dynamic size - save it
    if dynamic_size:
        options["min_size"] = dynamic_size
        print(f"[DEBUG] Parsed min_size = {dynamic_size} bytes ({dynamic_size / 1024 / 1024:.2f} MB)")

    # string or list
    query_str = " ".join(query) if isinstance(query, list) else query

    if query_str.lower() == "duplicates":
        options["duplicates"] = True

    # 🔥 Caso especial: fechas (ej. "Nov 11–17, 2024")
    date_match = re.findall(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:[\–-]| to )\d{1,2},?\s+\d{4}",
        user_prompt,
        re.IGNORECASE
    )

    if date_match:
        print(f"[DEBUG] Date(s) detected → {date_match}")
        options["dates"] = date_match

    return query, folder, mime_filter, options, mode



def resolve_path(file, drive_service, stop_root=None):
    path_parts = [file["name"]]
    parents = file.get("parents", [])

    while parents:
        parent_id = parents[0]
        if stop_root and parent_id == stop_root:
            break
        try:
            parent = drive_service.files().get(
                fileId=parent_id,
                fields="id, name, parents",
                supportsAllDrives=True
            ).execute()
        except Exception as e:
            # parent does not exist
            path_parts.append(f"[missing:{parent_id}]")
            break

        path_parts.append(parent["name"])
        parents = parent.get("parents", [])

        if stop_root and stop_root in parents:
            break

    return "/".join(reversed(path_parts))
#--------------------------------CLI---------------------

def interactive_cli():
    print("🚀 Drive Deep Search")
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)

    while True:
        # --- 1. Primera fase: búsqueda ---
        user_prompt = input("\n> Enter your search (or 'exit'): ").strip()
        if not user_prompt:
            continue
        if user_prompt.lower() in ("exit", "quit"):
            print("👋 Bye.")
            break

        # Usa el mismo parser que tu main
        query, folder, mime_filter, options, mode = interpret_prompt(user_prompt)

        # --- CASO DUPLICADOS ---
        if options.get("duplicates"):
            print("\n[DEBUG] Searching for duplicates...")
            # Aquí va tu lógica de duplicados igual que en tu versión original
            continue

        # --- FLUJO NORMAL ---
        results = search_drive(query, folder, mime_filter, mode)

        # Filtro por tamaño
        if "min_size" in options:
            min_size = options["min_size"]
            print(f"[DEBUG] Filtering results: keeping only >= {min_size / 1024 / 1024:.2f} MB")
            results = [f for f in results if int(f.get("size", 0)) >= min_size]

        ranked = []
        if results:
            ranked = rank_results(results, query)

            # detectar límite top-N
            number_map = {
                "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
            }
            limit = None
            for word, num in number_map.items():
                if word in user_prompt.lower():
                    limit = num
                    break
            match = re.search(r"\b\d+\b", user_prompt)
            if match:
                limit = int(match.group())
            if ("most recent" in user_prompt.lower() or "latest" in user_prompt.lower()) and not limit:
                limit = 3

            if limit:
                ranked.sort(key=lambda x: x[1].get("modifiedTime", ""), reverse=True)
                ranked = ranked[:limit]
                print(f"⚡ Filter applied: Keeping only {limit} most recent files")

            # imprimir resultados
            for score, item in ranked:
                print(f"\n📄 {item['name']} | ID: {item['id']}")
                print(f"Relevance: {score}%")
                print(f"Last modified: {item.get('modifiedTime', 'N/A')}")
                size_mb = round(int(item.get("size", 0)) / (1024 * 1024), 2) if "size" in item else "Unknown"
                print(f"Size: {size_mb} MB")

                if item["mimeType"] in [
                    "text/csv",
                    "application/vnd.ms-excel",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ]:
                    try:
                        request = drive_service.files().get_media(fileId=item['id'])
                        fh = BytesIO()
                        downloader = MediaIoBaseDownload(fh, request)
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                        fh.seek(0)
                        snippet = extract_snippet(fh, item["mimeType"], query)
                        print(f"   🔎 Snippet:\n{snippet}")
                    except Exception as e:
                        print(f"⚠️ Error downloading file: {e}")
                else:
                    print("   🔎 Snippet: ⚠️ Snippet not available for this file type.")

            print(f"\n✅ Total files found: {len(ranked)}")

        else:
            print("❌ No files found")
            continue

        # --- 2. Segunda fase: menú de acciones ---
        while True:
            cmd = input("\n👉 Enter a command (analyze/compare/help/back/exit): ").strip().lower()

            if cmd == "exit":
                print("👋 Exiting...")
                return

            elif cmd == "back":
                # volver a la búsqueda
                break

            elif cmd == "help":
                print("""
Available commands:
  analyze  -> Analyze a single file from the search results
  compare  -> Compare two files from the search results
  back     -> Go back to new search
  exit     -> Quit the program
""")

            elif cmd == "analyze":
                file_id = input("📂 Enter the Google Drive File ID (or number from results): ").strip()
                if file_id.isdigit():
                    idx = int(file_id) - 1
                    if 0 <= idx < len(ranked):
                        file_id = ranked[idx][1]["id"]
                    else:
                        print("⚠️ Invalid selection")
                        continue
                question = input("❓ Enter your question for the agent: ").strip()
                try:
                    df = download_file_as_dataframe(drive_service, file_id)
                    answer = ask_llm_about_dataframe(df, question)
                    print("\n📄 Detectado archivo analizable")
                    print("\n📌 Answer:\n", answer, "\n")
                except Exception as e:
                    print(f"⚠️ Error analyzing file: {e}")

            elif cmd == "compare":
                file_id1 = input("📂 Enter the first File ID (or number): ").strip()
                file_id2 = input("📂 Enter the second File ID (or number): ").strip()

                def resolve_id(choice):
                    if choice.isdigit():
                        idx = int(choice) - 1
                        if 0 <= idx < len(ranked):
                            return ranked[idx][1]["id"]
                    return choice

                file_id1 = resolve_id(file_id1)
                file_id2 = resolve_id(file_id2)

                question = input("❓ Enter your comparison question: ").strip()
                try:
                    df1 = download_file_as_dataframe(drive_service, file_id1)
                    df2 = download_file_as_dataframe(drive_service, file_id2)
                    comparison = compare_two_dataframes(df1, df2, question)
                    print("\n📌 Comparison:\n", comparison, "\n")
                except Exception as e:
                    print(f"⚠️ Error comparing files: {e}")

            else:
                print("❌ Unknown command. Type 'help' to see available options.\n")



# ------------------ MAIN ------------------
if __name__ == "__main__":
    interactive_cli()


# if __name__ == "__main__":
#     user_prompts = [                                                                        #ID     #RESULT
#         "Open the bartender role description.",                                             #0      OK -
#         "Find the Marketing / Social Media Lead responsibilities document.",                #1      OK -
#         "Locate the bar manager SOP—even if ‘manager’ is misspelled.",                      #2      ok partial in % -
#         "Surface any SOP that mentions ‘checking IDs’.",                                    #3      OK WITH % -
#         "Find documents with the heading ‘Proper Forms of ID Accepted’.",                   #4      OK -
#         "Open the Employee Organization Chart.",                                            #5      OK -
#         "Pull the latest ABC Liquor License.",                     #6      OK -
#         "Open the Tennessee Reseller’s Certificate that expires 1-31-2025.",                #7      ok pero checar expiracion -
#         "Locate our EIN letter/document.",                                                  #8      OK -
#         "Retrieve the ‘Metro liquor letter in lieu of certificate of occupancy’.",          #9      OK -
#         "Do we have a current health permit image or PDF? Open it.",                        #10     OK -
#         "List every permit or license that expires in the next 90 days.",                   #11     No -
#         "Open ‘Key Metrics to Track’.",                            #12     MASO -
#         "Find the file that mentions ‘Bev-INCO rating’.",                                   #13     MASO /
#         "Locate the table where ‘Sale per check’ is set to $22.",                           #14     OK -
#         "Show all documents mentioning ‘inventory turnover rate’.",                         #15     MASO /
#         "Open the Sculpture Hospitality weekly report for May 20–26, 2025.",                #16     OK -
#         "Show files with the phrase ‘Target Stock on Hand in Weeks’.",                      #17     MASO -
#         "Open the beverage price list image for beers and seltzers.",                       #18     OK -
#         "List the three most recent inventory or stock reports.",                           #19     OK -
#         "Show only Word docs (.docx) inside ‘5- Roles & Titles’.",                          #20     OK /
#         "Find any file larger than 0.5 MB in the permits directory.",                       #21     OK /
#         "Show duplicates or near-duplicates by title (e.g., ‘Key Metrics to Track’).",      #22     OK -
#         "Show everything related to ID-checking policy, including attachments and images.", #23     OK /
#         "Locate any document that includes the permit numbers 23-28424 or 23-28425."        #24     OK /
#     ]
#
#     # prompt
#     user_prompt = user_prompts[11]
#
#     query, folder, mime_filter, options, mode= interpret_prompt(user_prompt)
#
#
#     # ------------------ 🔥 CASO ESPECIAL DUPLICADOS ------------------
#     if "duplicate" in user_prompt.lower():
#         print("\n[DEBUG] Searching for duplicates...")
#
#         # ✅ Caso 1: specific foler
#         if folder:
#             target_folders = [folder]
#         else:
#             # ✅ Caso 2: no folder
#             target_folders = [
#                 "1JgvFkJUrzuwhpggeOSrH1fgBhTjHYyBD",
#                 "17kUIyMg19PJ_E0Pewo9PZZeLw9z2pxPD"
#             ]
#
#         all_files = []
#         for f_id in target_folders:
#             all_files.extend(list_files_recursive(f_id))
#
#         # Filter by allowed
#         ALLOWED_MIME_TYPES = {
#             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#             "application/msword",
#             "application/pdf",
#             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#             "application/vnd.ms-excel",
#             "application/vnd.openxmlformats-officedocument.presentationml.presentation",
#             "application/vnd.ms-powerpoint",
#             "text/plain"
#         }
#         all_files = [f for f in all_files if f["mimeType"] in ALLOWED_MIME_TYPES]
#
#         print(f"[DEBUG] Retrieved {len(all_files)} files total from {len(target_folders)} folder(s).")
#
#         if all_files:
#             groups = group_near_duplicates(all_files, threshold=85)
#             if groups:
#                 for g in groups:
#                     print("\n🔁 Duplicate group:")
#                     for f in g:
#                         path = resolve_path(f, drive_service, stop_root="17kUIyMg19PJ_E0Pewo9PZZeLw9z2pxPD")
#                         print(f"   - {f['name']} | ID: {f['id']} | Path: {path} | Last modified: {f.get('modifiedTime', 'N/A')}")
#
#                 print(f"\n✅ Total duplicate groups found: {len(groups)}")
#             else:
#                 print("❌ No duplicates found")
#         else:
#             print("❌ No files found in target folders.")
#
#
#
#     # ------------------ NORMAL WORKLFLOW ------------------
#     else:
#
#         results = search_drive(query, folder, mime_filter, mode)
#
#         # --- 🔥 Apply dynamic size filter ---
#         if "min_size" in options:
#             min_size = options["min_size"]
#             print(f"[DEBUG] Filtering results: keeping only >= {min_size / 1024 / 1024:.2f} MB")
#             results = [f for f in results if int(f.get("size", 0)) >= min_size]
#
#         if results:
#             ranked = rank_results(results, query)
#
#             # --- N most /recent ---
#             import re
#
#             number_map = {
#                 "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
#                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
#             }
#
#             limit = None
#
#             # search number-word
#             for word, num in number_map.items():
#                 if word in user_prompt.lower():
#                     limit = num
#                     break
#
#             # Search number as digit
#             match = re.search(r"\b\d+\b", user_prompt)
#             if match:
#                 limit = int(match.group())
#
#             # if  "most recent" o "latest" without number → default=3
#             if ("most recent" in user_prompt.lower() or "latest" in user_prompt.lower()) and not limit:
#                 limit = 3
#
#             # apply cut
#             if limit:
#                 ranked.sort(key=lambda x: x[1].get("modifiedTime", ""), reverse=True)
#                 ranked = ranked[:limit]
#                 print(f"⚡ Filter applied: Keeping only {limit} most recent files")
#
#             for score, item in ranked:
#                 print(f"\n📄 {item['name']} | ID: {item['id']}")
#                 print(f"Relevance: {score}%")
#                 print(f"Last modified: {item.get('modifiedTime', 'N/A')}")
#                 size_mb = round(int(item.get("size", 0)) / (1024 * 1024), 2) if "size" in item else "Unknown"
#                 print(f"Size: {size_mb} MB")
#
#                 if item["mimeType"] in [
#                     "text/csv",
#                     "application/vnd.ms-excel",
#                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#                 ]:
#                     try:
#                         request = drive_service.files().get_media(fileId=item['id'])
#                         fh = BytesIO()
#                         downloader = MediaIoBaseDownload(fh, request)
#                         done = False
#                         while not done:
#                             status, done = downloader.next_chunk()
#                         fh.seek(0)
#
#                         snippet = extract_snippet(fh, item["mimeType"], query)
#                         print(f"   🔎 Snippet:\n{snippet}")
#                     except Exception as e:
#                         print(f"⚠️ Error downloading file: {e}")
#                 else:
#                     print("   🔎 Snippet: ⚠️ Snippet not available for this file type.")
#
#             print(f"\n✅ Total files found: {len(ranked)}")
#
#         else:
#             print("❌ No files found")