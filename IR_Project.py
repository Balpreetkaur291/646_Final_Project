!pip install -U sentence-transformers

!pip install -U torch transformers scikit-learn
!pip install rouge
!pip install numpy==1.26

!pip install faiss-cpu ijson google-generativeai

!pip install pyserini

import pandas as pd
import random
import json
import requests
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

import torch

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

from google.colab import drive
drive.mount('/content/drive')

!pip install google-generativeai --upgrade

import requests
import json

def load_lamp4_dataset(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"Error downloading data: {e}")
        return None

from tqdm import tqdm
import random

top_k_articles = []

lamp4_data = []
lamp4_subset=[]


import random
from tqdm import tqdm

url = "https://ciir.cs.umass.edu/downloads/LaMP/LaMP_4/train/train_questions.json"

lamp4_data = load_lamp4_dataset(url)

if lamp4_data is None:
    print("Failed to load dataset. Exiting.")
else:
    subset_size = 300
    lamp4_subset = random.sample(lamp4_data, subset_size)

file_path = '/content/drive/MyDrive/IR Project/Project Files/lamp_4_data.json'

with open(file_path, "w", encoding="utf-8") as outfile:
    json.dump(lamp4_subset, outfile, indent=4)

with open(file_path, "r", encoding="utf-8") as file:
        lamp4_subset = json.load(file)

lamp4_subset = random.sample(lamp4_subset, 100)

import numpy as np
import pandas as pd
import faiss
import ijson
import google.generativeai as genai
from transformers import AutoTokenizer, AutoModel
import torch
import json

genai.configure(api_key="AIzaSyDb361_mnQ_6qrckEv_eFgu1mB5dO9II0E")


# generate variant of input text

def generate(given_line, num_variants=3):
    """
    Generates multiple hypothetical versions of the input query using the Gemini model.
    """
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = []
    for _ in range(num_variants):
        response_t = model.generate_content(given_line)
        response.append(response_t.text)
    return response

def encode(model, tokenizer, text):
    """
    Encodes a single text input into a dense embedding using the Contriever model.
    """
    inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.pooler_output[0].numpy()

def create_index_in_batches(df, encoder, tokenizer, batch_size=100):
    """
    Processes the user profiles in batches to create a FAISS index.
    """
    index = None
    for start in range(0, len(df), batch_size):
        batch = df[start: start + batch_size]
        embeddings = [encode(encoder, tokenizer, text) for text in batch['text']]
        embeddings = np.array(embeddings).astype("float32")

        if index is None:
            index = faiss.IndexFlatL2(embeddings.shape[1])
            index = faiss.IndexIDMap(index)


        index.add_with_ids(embeddings, batch['id'].values)

    return index

def initialize_encoder():
    tokenizer = AutoTokenizer.from_pretrained("facebook/contriever")
    model = AutoModel.from_pretrained("facebook/contriever")
    return model, tokenizer

encoder_model, encoder_tokenizer = initialize_encoder()

from tqdm import tqdm
import json
import os

def process_data_in_batches(
    lamp4_subset, encoder, tokenizer, batch_size=100, output_file="/content/drive/MyDrive/IR Project/Project Files/top_k_articles.json"
):
    """
    Processes the data in batches to find top-k relevant documents for each query.
    Saves results to the output file after every 10 articles.
    """
    top_k_articles = []  # To store the final results

    # Iterate over each item in the list with progress tracking
    for idx, item in enumerate(tqdm(lamp4_subset, desc="Processing items")):
        try:
            original_query = item['input']  # Assuming 'input' is a key in your JSON
            given_line = original_query[:47]  # Truncate or process the query as needed
            new_query = f"Paraphrase the article: {given_line}"

            # Generate hypothetical versions
            response = generate(new_query)

            # Access the user profile data
            user_profile = item['profile']

            # Debugging: Check the format of user_profile and clean it
            if isinstance(user_profile, str):
                user_profile = json.loads(user_profile.replace("'", "\""))  # Ensure valid JSON format
            elif not isinstance(user_profile, list):
                raise ValueError(f"Expected a list for user_profile, got {type(user_profile)}")

            # Check if user_profile is empty
            if len(user_profile) == 0:
                raise ValueError("user_profile is empty.")

            # Create a DataFrame from the profile data
            df_profile = pd.DataFrame(user_profile)

            # Create the FAISS index in smaller batches
            index = create_index_in_batches(df_profile, encoder, tokenizer, batch_size)

            # Compute dense vector for the query
            dense_vector = np.mean(
                [encode(encoder, tokenizer, t) for t in [given_line] + response], axis=0
            )
            dense_vector = dense_vector.reshape(1, -1).astype("float32")

            # Perform dense search
            length_profile = len(user_profile)
            k = min(3, max(1, length_profile // 2))  # Determine k based on profile size
            distances, indices = index.search(dense_vector, k)

            # Flatten the top-k indices
            top_k_indices = [str(idx) for idx in indices[0]]

            # Match the top_k_indices with user_profile['id'] and extract additional information
            matched_articles = [
                {"text": profile['text'], "title": profile['title'], "id": profile['id']}
                for profile in user_profile if str(profile['id']) in top_k_indices
            ]

            # Append the matched articles to the final results
            top_k_articles.append({
                "id": item['id'],  # Original item ID
                "input": item['input'],  # Original query
                "top_k_articles": matched_articles  # Matched articles with detailed information
            })

            # Save results after every 50 articles
            if (idx + 1) % 50 == 0 or (idx + 1) == len(lamp4_subset):
                temp_output_file = output_file.replace(".json", f"_{idx + 1}.json")
                with open(temp_output_file, "w", encoding="utf-8") as outfile:
                    json.dump(top_k_articles, outfile, indent=4)
                print(f"Saved progress to {temp_output_file}")

        except Exception as e:
            print(f"Error processing item {idx}: {e}")
            continue  # Skip this entry and move to the next one

    # Final save to the main output file
    with open(output_file, "w", encoding="utf-8") as outfile:
        json.dump(top_k_articles, outfile, indent=4)

    print(f"Final results saved to {output_file}")

process_data_in_batches(lamp4_subset, encoder_model, encoder_tokenizer, batch_size=50)

!pip uninstall -y sentence-transformers
!pip install -U sentence-transformers
!pip install -U torch transformers scikit-learn
!pip install rouge
!pip install -U torch transformers scikit-learn
!pip install rouge
!pip uninstall -y numpy
!pip install numpy==1.26
import pandas as pd
import random
import json
import requests
#from rouge import Rouge
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# Commented out IPython magic to ensure Python compatibility.
drive_folder = '/content/drive/Shareddrives/682_Drive'
# Adjust this line to be the assignment1 folder in your google drive
notebook_folder = drive_folder + '/646_Project'
# %cd {notebook_folder}

folder_path = notebook_folder
file_path = f'{folder_path}/lamp_4_data.json'
def save_dataset(data):
  sampled_data = random.sample(data, 100)
  data_df = pd.DataFrame(sampled_data)
  data_df.to_csv(file_path)

def fetch_and_print_json(url):
    try:

        response = requests.get(url)
        response.raise_for_status()

        data = response.json()



        if isinstance(data, dict):
            print("JSON is a dictionary. Here are the keys:")
            print(data.keys())
            print("\nSample content:")
            print(data)
            save_dataset(data)

        elif isinstance(data, list):
            print("JSON is a list. Length of list:", len(data))
            print("\nFirst item in the list:")
            print(data[0])
            save_dataset(data)

        else:
            print("Unexpected JSON format. Printing the data:")
            print(data)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching JSON from URL: {e}")
    except Exception as e:
        print(f"Error processing JSON: {e}")


reference_url = "https://ciir.cs.umass.edu/downloads/LaMP/LaMP_4/train/train_questions.json"

fetch_and_print_json(reference_url)

from sentence_transformers import SentenceTransformer

model = SentenceTransformer('AnnaWegmann/Style-Embedding')
print("Model Loaded succesfully!")

from numpy import mean

# Define a function to compute the average style embedding
def compute_average_embedding(profile, model):
    # Extract text content from each profile article
    profile_texts = [article['text'] for article in profile]

    # Compute embeddings for all articles
    embeddings = model.encode(profile_texts, convert_to_tensor=True)

    # Calculate the average embedding
    avg_embedding = embeddings.mean(axis=0)

    return avg_embedding

from sentence_transformers import util

# Define a function to find top-k relevant articles
def find_top_k_articles(profile, avg_embedding, model, k=5):
    # Extract texts and compute embeddings
    profile_texts = [article['text'] for article in profile]
    profile_embeddings = model.encode(profile_texts, convert_to_tensor=True)

    # Compute cosine similarity with average embedding
    similarities = util.cos_sim(profile_embeddings, avg_embedding).squeeze(1)
    # Sort articles by similarity
    top_k_indices = similarities.argsort(descending=True)[:k]
    top_k_articles = [profile[i] for i in top_k_indices]
    return top_k_articles

def safe_json_loads(value):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        print(f"Invalid JSON: {value}")
        return None

import pandas as pd
import json
import ast
from tqdm import tqdm

# Load the JSON file
with open(file_path, 'r') as f:
    data = json.load(f)

# Normalize the data into a DataFrame, but do not flatten 'profile'
# Use json_normalize for other fields, but leave 'profile' as-is
def safe_literal_eval(value):
    """ Safely convert string to list or dictionary """
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        print(f"Invalid format in profile: {value}")
        return value  # return as is if there's an error

# If 'profile' is a string representation of a list, convert it back
for entry in data:
    if isinstance(entry.get('profile'), str):
        entry['profile'] = safe_literal_eval(entry['profile'])

# Convert the data into a DataFrame
loaded_df = pd.DataFrame(data)


# Convert DataFrame back to a list of dictionaries
data = loaded_df.to_dict(orient="records")

# Process each item and find top-k articles
results = []
k = 5

for item in tqdm(data, desc="Finding top-k articles from user profiles:"):
    profile = item['profile']
    avg_embedding = compute_average_embedding(profile, model)
    top_k_articles = find_top_k_articles(profile, avg_embedding, model, k)
    results.append({
        "id": item['id'],
        "input": item['input'],
        "top_k_articles": top_k_articles
    })

# Example: Print the first result
print(results[0])

import json
top_k_path = f'{folder_path}/top_k_articles_style_300.json'
#
# Save results to a file
with open(top_k_path, "w") as f:
    json.dump(results, f, indent=4)

tokenizer = AutoTokenizer.from_pretrained("google/flan-t5-base")
model = AutoModelForSeq2SeqLM.from_pretrained("google/flan-t5-base")

def load_reference_outputs(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data['golds']
    except requests.exceptions.RequestException as e:
        print(f"Error downloading reference outputs: {e}")
        return None

reference_url = "https://ciir.cs.umass.edu/downloads/LaMP/LaMP_4/train/train_outputs.json"
reference_outputs = load_reference_outputs(reference_url)

def generate_headline(input_text):
    inputs = tokenizer(input_text, return_tensors="pt", max_length=512, truncation=True)
    outputs = model.generate(**inputs, max_length=64, num_beams=4)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

from tqdm import tqdm

def generate_output_using_LLM(top_k_data, top_k_data_bm25):
    generated_headlines = []
    counter = 0

    for item in tqdm(top_k_data, desc="Generating headlines using LLM"):
        input_article = item["input"]
        top_k_articles = item["top_k_articles"]

        # Ensure consistent types for ID matching
        item_id = str(item["id"])  # Convert to string for matching

        # Find corresponding BM25 entry
        top_k_articles_bm25_item = next(
            (bm25_item for bm25_item in top_k_data_bm25 if bm25_item["id"] == item_id),
            None
        )

        # Handle missing BM25 data gracefully
        if not top_k_articles_bm25_item:
            print(f"No matching BM25 data for id: {item_id}")
            continue
        counter+=1
        top_k_articles_bm25 = top_k_articles_bm25_item["top_k_articles"]

        # Combine context: 1 article from each source
        context_articles = top_k_articles[:1] + top_k_articles_bm25[:1]
        #context_articles = top_k_articles_bm25[:2]
        context = "\n".join(
            [f"Title: {a['title']}\nText: {a['text']}" for a in context_articles]
        )

        # Create input text
        input_text = f"{input_article}\nGiven past user profile context:\n{context}"
        print(input_text)
        # Generate headline
        headline = generate_headline(input_text)

        # Append result
        generated_headlines.append({
            "id": item["id"],
            "output": headline
        })
    print(f"Genearted headlines for {counter} articles ! ")
    return generated_headlines

!pip install rouge-score

from rouge_score import rouge_scorer

def evaluate_rouge(generated_headlines, reference_outputs):
    """
    Evaluates ROUGE scores for generated headlines against reference outputs.

    Args:
        generated_headlines (list): A list of dictionaries with "id" and "output" keys.
        reference_outputs (list): A list of dictionaries with "id" and "output" keys.

    Returns:
        dict: Average ROUGE-1, ROUGE-2, and ROUGE-L scores across all evaluated headlines.
    """
    scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
    scores = {
        "rouge1": [],
        "rouge2": [],
        "rougeL": []
    }

    for gen_headline in generated_headlines:
        ref_output = next(
            (ref for ref in reference_outputs if ref["id"] == str(gen_headline["id"])),
            None
        )

        if ref_output:
            score = scorer.score(gen_headline["output"], ref_output["output"])
            scores["rouge1"].append(score["rouge1"].fmeasure)
            scores["rouge2"].append(score["rouge2"].fmeasure)
            scores["rougeL"].append(score["rougeL"].fmeasure)
        else:
            print(f"Warning: No reference found for ID {gen_headline['id']}")

    avg_scores = {metric: (sum(scores[metric]) / len(scores[metric]) if scores[metric] else 0)
                  for metric in scores}

    return avg_scores

top_k_path = f"{folder_path}/top_k_articles_style_300.json"
with open(top_k_path, "r") as f:
    top_k_data = json.load(f)

top_k_path_bm25 = f"{folder_path}/top_k_articles_dense_search_100.json"
with open(top_k_path_bm25, "r") as f:
    top_k_data_bm25 = json.load(f)

generated_headlines = generate_output_using_LLM(top_k_data, top_k_data_bm25)
rouge_scores = evaluate_rouge(generated_headlines, reference_outputs)
generated_headlines_write = f"{folder_path}/generated_headlines_dense_100.json"
with open(generated_headlines_write, "w") as f:
    json.dump(generated_headlines, f, indent=4)

generated_headlines_read = (f"{folder_path}/generated_headlines_hybrid.json")
with open(generated_headlines_read, "r") as f:
    generated_headlines = json.load(f)
rouge_scores = evaluate_rouge(generated_headlines, reference_outputs)
print("ROUGE Evaluation Results:", rouge_scores)

print(reference_outputs)
