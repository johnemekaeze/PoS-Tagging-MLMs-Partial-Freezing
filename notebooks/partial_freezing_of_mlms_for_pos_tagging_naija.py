# -*- coding: utf-8 -*-
"""Partial Freezing of MLMs for PoS Tagging-Naija.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1IqZTVVXVN29hGysGSszyn2kgEndi0EZD

# Topic: Partial Freezing of MLMs for PoS Tagging: A Case of Naija Pidgin
"""

!pip -q install datasets transformers conllu torch

"""# Task 1: Dataset Preparation and Baseline Model Training

## Loading Data
"""

import random
import numpy as np
import torch

SEED = 42

random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
torch.backends.cudnn.deterministic = True

import requests, zipfile, io, os

# GitHub raw URL (direct to the ZIP)
url = "https://github.com/johnemekaeze/PoS-Tagging-MLMs-Partial-Freezing/raw/main/data/ud-treebanks-v2.16-subset.zip"

# Download and extract to a folder
response = requests.get(url)
z = zipfile.ZipFile(io.BytesIO(response.content))
z.extractall("ud_subset")  # this creates a folder with all sub-treebanks

import os

root_path = "ud_subset/ud-treebanks-v2.16-subset"
treebanks = sorted(os.listdir(root_path))
print("Available treebanks:")
treebanks

from conllu import parse_incr

def load_conllu_sentences(path):
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for tokenlist in parse_incr(f):
            tokens = [token["form"].lower() for token in tokenlist if type(token["id"]) == int]
            upos   = [token["upos"] for token in tokenlist if type(token["id"]) == int]
            data.append((tokens, upos))
    return data

tb_name = "UD_Naija-NSC"
train_path = os.path.join(root_path, tb_name, "pcm_nsc-ud-train.conllu")
test_path  = os.path.join(root_path, tb_name, "pcm_nsc-ud-test.conllu")
dev_path   = os.path.join(root_path, tb_name, "pcm_nsc-ud-dev.conllu")

train_sentences = load_conllu_sentences(train_path)
test_sentences  = load_conllu_sentences(test_path)
dev_sentences   = load_conllu_sentences(dev_path)

# Example
print(f"{len(train_sentences)} sentences loaded.")
print("Tokens:", train_sentences[0][0])
print("UPOS  :", train_sentences[0][1])

train_sentences[:10]

print(f"Number of training examples: {len(train_sentences)}")
print(f"Number of test examples: {len(test_sentences)}")
print(f"Number of dev examples: {len(dev_sentences)}")

"""## Tokenization"""

import random

# Set seed for reproducibility
random.seed(42)

train_subset = train_sentences #random.sample(train_sentences, int(0.2 * len(train_sentences)))
dev_subset   = dev_sentences #random.sample(dev_sentences,   int(0.2 * len(dev_sentences)))
test_subset  = test_sentences #random.sample(test_sentences,  int(0.2 * len(test_sentences)))

# Get full set of UPOS tags from training split
all_tags = sorted({tag for _, tags in train_subset for tag in tags})
tag2id = {tag: i for i, tag in enumerate(all_tags)}
id2tag = {i: tag for tag, i in tag2id.items()}

from transformers import AutoTokenizer

# Load a multilingual DistilBERT tokenizer
tokenizer = AutoTokenizer.from_pretrained("distilbert-base-multilingual-cased")

def tokenize_and_align(example, label_all_tokens=False):
    tokens, labels = example
    tokenized = tokenizer(tokens,
                          is_split_into_words=True,
                          truncation=True,
                          max_length=128)

    word_ids = tokenized.word_ids()
    aligned_labels = []
    previous_word_idx = None

    for word_idx in word_ids:
        if word_idx is None:
            aligned_labels.append(-100)
        elif word_idx != previous_word_idx:
            aligned_labels.append(tag2id[labels[word_idx]])
        else:
            aligned_labels.append(tag2id[labels[word_idx]] if label_all_tokens else -100)
        previous_word_idx = word_idx

    tokenized["labels"] = aligned_labels
    return tokenized

from datasets import Dataset

# Wrap into HuggingFace Datasets
train_dataset = Dataset.from_list([{"tokens": t, "upos": u} for t, u in train_subset])
dev_dataset   = Dataset.from_list([{"tokens": t, "upos": u} for t, u in dev_subset])
test_dataset  = Dataset.from_list([{"tokens": t, "upos": u} for t, u in test_subset])

# Tokenize and align
train_tok = train_dataset.map(lambda ex: tokenize_and_align((ex["tokens"], ex["upos"])),
                              batched=False)
dev_tok   = dev_dataset.map(lambda ex: tokenize_and_align((ex["tokens"], ex["upos"])),
                            batched=False)
test_tok  = test_dataset.map(lambda ex: tokenize_and_align((ex["tokens"], ex["upos"])),
                             batched=False)

print("Original Tokens:", train_subset[0][0])
print("Tokenized Version:", tokenizer.convert_ids_to_tokens(train_tok[0]["input_ids"]))
print("Labels:", [id2tag[label] if label != -100 else -100 for label in train_tok[0]["labels"]])

"""## Fine-tuning a Distilled Model (Baseline)"""

from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    DataCollatorForTokenClassification,
    TrainingArguments,
    Trainer,
)
import numpy as np
from datasets import Dataset
import warnings
warnings.filterwarnings("ignore")


# 2) Load tokenizer & model
model_name = "distilbert-base-multilingual-cased"
tokenizer  = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForTokenClassification.from_pretrained(
    model_name,
    num_labels=len(tag2id),
    id2label={i: t for t, i in tag2id.items()},
    label2id=tag2id,
)

# 3) Data collator to pad and align labels
data_collator = DataCollatorForTokenClassification(tokenizer)

# 4) Define metrics function (here: token accuracy)
def compute_metrics(p):
    preds = np.argmax(p.predictions, axis=2)
    labels = p.label_ids
    # only consider non -100 labels
    mask = labels != -100
    acc = (preds[mask] == labels[mask]).astype(np.float32).mean().item()
    return {"accuracy": acc}

# 5) Training arguments
training_args = TrainingArguments(
    output_dir="./baseline_distilbert",
    eval_strategy="epoch",      # skip eval for the fastest baseline
    save_strategy="no",            # skip checkpointing
    learning_rate=5e-5,
    per_device_train_batch_size=16,
    num_train_epochs=5,
    weight_decay=0.01,
    logging_steps=50,
)

# 6) Initialize Trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_tok,
    eval_dataset=dev_tok,
    tokenizer=tokenizer,
    data_collator=data_collator,
    compute_metrics=compute_metrics,
)

# 7) Train!
trainer.train()

# Baseline evaluation on a small dev split
metrics = trainer.evaluate(eval_dataset=dev_tok)
print("Evaluation accuracy:", metrics["eval_accuracy"])

"""# Task 2: Model Adjustment and Partial Freezing

## Layer Freezing
"""

from transformers import AutoModelForTokenClassification

def freeze_layers(model, freeze_strategy="first_k", k=2):
    """
    Freeze layers of a DistilBERT model based on the given strategy.

    Args:
        model: An instance of AutoModelForTokenClassification based on DistilBERT.
        freeze_strategy: Strategy to freeze layers. Options:
            - "all_encoder": Freeze all encoder layers.
            - "first_k": Freeze the first k encoder layers.
            - "last_k": Freeze the last k encoder layers.
            - "alternating": Freeze alternating layers (even-indexed).
        k: Number of layers to freeze for "first_k" or "last_k" strategies.
    """


    layers = model.distilbert.transformer.layer

    if freeze_strategy == "all_encoder":
        for layer in layers:
            for param in layer.parameters():
                param.requires_grad = False

    elif freeze_strategy == "first_k":
        for i, layer in enumerate(layers):
            if i < k:
                for param in layer.parameters():
                    param.requires_grad = False

    elif freeze_strategy == "alternating":
        for i, layer in enumerate(layers):
            if i % 2 == 0:
                for param in layer.parameters():
                    param.requires_grad = False
    else:
        raise ValueError(f"Unknown freeze_strategy: {freeze_strategy}")

model.distilbert.transformer.layer

len(model.distilbert.transformer.layer)

"""## Freeze all encoder layers"""

from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    DataCollatorForTokenClassification,
    TrainingArguments,
    Trainer,
)
import numpy as np
from datasets import Dataset
import warnings
warnings.filterwarnings("ignore")


# 2) Load tokenizer & model
model_name = "distilbert-base-multilingual-cased"
tokenizer  = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForTokenClassification.from_pretrained(
    model_name,
    num_labels=len(tag2id),
    id2label={i: t for t, i in tag2id.items()},
    label2id=tag2id,
)

# 3) Apply partial-freeze
freeze_layers(model, freeze_strategy="all_encoder")

# 4) Prepare data collator
data_collator = DataCollatorForTokenClassification(tokenizer)

# 5) Metrics function
def compute_metrics(p):
    preds = np.argmax(p.predictions, axis=2)
    labels = p.label_ids
    mask = labels != -100
    acc = (preds[mask] == labels[mask]).astype(np.float32).mean().item()
    return {"accuracy": acc}

# 6) Training arguments
training_args = TrainingArguments(
    output_dir="./frozen_first_2_distilbert",
    eval_strategy="epoch",
    save_strategy="no",
    learning_rate=5e-5,
    per_device_train_batch_size=16,
    num_train_epochs=5,
    weight_decay=0.01,
    logging_steps=50,
)

# 7) Initialize Trainer with the already‑frozen model
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_tok,
    eval_dataset=dev_tok,             # now you can also evaluate each epoch
    tokenizer=tokenizer,
    data_collator=data_collator,
    compute_metrics=compute_metrics,
)

# 8) Train!
trainer.train()

# 8) Baseline evaluation on a small dev split
metrics = trainer.evaluate(eval_dataset=dev_tok)
print("Evaluation accuracy:", metrics["eval_accuracy"])

"""## Freeze first 2 layers"""

from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    DataCollatorForTokenClassification,
    TrainingArguments,
    Trainer,
)
import numpy as np
from datasets import Dataset
import warnings
warnings.filterwarnings("ignore")


# 2) Load tokenizer & model
model_name = "distilbert-base-multilingual-cased"
tokenizer  = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForTokenClassification.from_pretrained(
    model_name,
    num_labels=len(tag2id),
    id2label={i: t for t, i in tag2id.items()},
    label2id=tag2id,
)

# 3) Apply partial-freeze
freeze_layers(model, freeze_strategy="first_k", k=2)

# 4) Prepare data collator
data_collator = DataCollatorForTokenClassification(tokenizer)

# 5) Metrics function
def compute_metrics(p):
    preds = np.argmax(p.predictions, axis=2)
    labels = p.label_ids
    mask = labels != -100
    acc = (preds[mask] == labels[mask]).astype(np.float32).mean().item()
    return {"accuracy": acc}

# 6) Training arguments
training_args = TrainingArguments(
    output_dir="./frozen_first_2_distilbert",
    eval_strategy="epoch",
    save_strategy="no",
    learning_rate=5e-5,
    per_device_train_batch_size=16,
    num_train_epochs=5,
    weight_decay=0.01,
    logging_steps=50,
)

# 7) Initialize Trainer with the already‑frozen model
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_tok,
    eval_dataset=dev_tok,             # now you can also evaluate each epoch
    tokenizer=tokenizer,
    data_collator=data_collator,
    compute_metrics=compute_metrics,
)

# 8) Train!
trainer.train()

# 8) Baseline evaluation on a small dev split
metrics = trainer.evaluate(eval_dataset=dev_tok)
print("Evaluation accuracy:", metrics["eval_accuracy"])

"""## Freeze first 4 layers"""

from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    DataCollatorForTokenClassification,
    TrainingArguments,
    Trainer,
)
import numpy as np
from datasets import Dataset
import warnings
warnings.filterwarnings("ignore")


# 2) Load tokenizer & model
model_name = "distilbert-base-multilingual-cased"
tokenizer  = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForTokenClassification.from_pretrained(
    model_name,
    num_labels=len(tag2id),
    id2label={i: t for t, i in tag2id.items()},
    label2id=tag2id,
)

# 3) Apply partial-freeze
freeze_layers(model, freeze_strategy="first_k", k=4)

# 4) Prepare data collator
data_collator = DataCollatorForTokenClassification(tokenizer)

# 5) Metrics function
def compute_metrics(p):
    preds = np.argmax(p.predictions, axis=2)
    labels = p.label_ids
    mask = labels != -100
    acc = (preds[mask] == labels[mask]).astype(np.float32).mean().item()
    return {"accuracy": acc}

# 6) Training arguments
training_args = TrainingArguments(
    output_dir="./frozen_first_4_distilbert",
    eval_strategy="epoch",
    save_strategy="no",
    learning_rate=5e-5,
    per_device_train_batch_size=16,
    num_train_epochs=5,
    weight_decay=0.01,
    logging_steps=50,
)

# 7) Initialize Trainer with the already‑frozen model
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_tok,
    eval_dataset=dev_tok,             # now you can also evaluate each epoch
    tokenizer=tokenizer,
    data_collator=data_collator,
    compute_metrics=compute_metrics,
)

# 8) Train!
trainer.train()

# Baseline evaluation on a small dev split
dev_hf = dev_tok
metrics = trainer.evaluate(eval_dataset=dev_hf)
print("Evaluation accuracy:", metrics["eval_accuracy"])

"""## Alternate freezing strategy"""

from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    DataCollatorForTokenClassification,
    TrainingArguments,
    Trainer,
)
import numpy as np
from datasets import Dataset
import warnings
warnings.filterwarnings("ignore")


# Load tokenizer & model
model_name = "distilbert-base-multilingual-cased"
tokenizer  = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForTokenClassification.from_pretrained(
    model_name,
    num_labels=len(tag2id),
    id2label={i: t for t, i in tag2id.items()},
    label2id=tag2id,
)

# Apply partial-freeze
freeze_layers(model, freeze_strategy="alternating")

# Prepare data collator
data_collator = DataCollatorForTokenClassification(tokenizer)

# Metrics function
def compute_metrics(p):
    preds = np.argmax(p.predictions, axis=2)
    labels = p.label_ids
    mask = labels != -100
    acc = (preds[mask] == labels[mask]).astype(np.float32).mean().item()
    return {"accuracy": acc}

# Training arguments
training_args = TrainingArguments(
    output_dir="./frozen_alt_distilbert",
    eval_strategy="epoch",
    save_strategy="no",
    learning_rate=5e-5,
    per_device_train_batch_size=16,
    num_train_epochs=5,
    weight_decay=0.01,
    logging_steps=50,
)

# Initialize Trainer with the already‑frozen model
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_tok,
    eval_dataset=dev_tok,
    tokenizer=tokenizer,
    data_collator=data_collator,
    compute_metrics=compute_metrics,
)

# Train
trainer.train()

# 8) Baseline evaluation on a small dev split
dev_hf = dev_tok
metrics = trainer.evaluate(eval_dataset=dev_hf)
print("Evaluation accuracy:", metrics["eval_accuracy"])

"""# Task 3: Analysis and Comparison

## Analysis of Parameters
"""

import torch
from transformers import AutoModelForTokenClassification
import pandas as pd

# Define freeze function
def freeze_layers(model, strategy, k=0):
    # Unfreeze all first
    for param in model.parameters():
        param.requires_grad = True
    layers = model.distilbert.transformer.layer
    if strategy == "all_encoder":
        for layer in layers:
            for param in layer.parameters():
                param.requires_grad = False
    elif strategy == "first_k":
        for i, layer in enumerate(layers):
            if i < k:
                for param in layer.parameters():
                    param.requires_grad = False
    elif strategy == "alternating":
        for i, layer in enumerate(layers):
            if i % 2 == 0:
                for param in layer.parameters():
                    param.requires_grad = False

# Load base model name
model_name = "distilbert-base-multilingual-cased"
strategies = [
    ("No Freeze", None, 0),
    ("Freeze All", "all_encoder", 0),
    ("Freeze First 2", "first_k", 2),
    ("Freeze First 4", "first_k", 4),
    ("Alternating Freeze", "alternating", 0),
]

results = []

for name, strat, k in strategies:
    model = AutoModelForTokenClassification.from_pretrained(
        model_name, num_labels=10  # dummy num_labels
    )
    if strat:
        freeze_layers(model, strat, k)
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    results.append({
        "Strategy": name,
        "Total Params": total_params,
        "Trainable Params": trainable_params,
        "Trainable (%)": trainable_params / total_params * 100
    })

df_params = pd.DataFrame(results)

# Display the DataFrame to the user
display(df_params)

"""## Model Performance Across Freezing Strategies"""

from matplotlib import pyplot as plt
import seaborn as sns
import pandas as pd

# Example results - replace with your actual evaluation metrics
data = {
    "Strategy": ["Baseline", "Freeze All", "Freeze First 2", "Freeze First 4", "Alternating Freeze"],
    "Dev Accuracy": [98.2, 93.2, 98.1, 97.7, 98.2]
}
df_results = pd.DataFrame(data)

# Display the DataFrame to the user
display(df_results)

# Create horizontal bar chart with Dark2 palette
palette = sns.color_palette("Dark2", n_colors=len(df_results))
plt.figure(figsize=(8, 4))
ax = df_results.set_index('Strategy')['Dev Accuracy'].plot(
    kind='barh',
    color=palette
)

# Annotate each bar with its accuracy value
for i, (strategy, accuracy) in enumerate(zip(df_results['Strategy'], df_results['Dev Accuracy'])):
    ax.text(accuracy + 0.005, i, f"{accuracy:.1f}", va='center')

# Remove top and right spines
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

plt.xlabel("Evaluation Accuracy (%)")
plt.title("Model Performance Across Freezing Strategies (Naija)")
plt.xlim(0, 100.0)  # ensure space for labels on the right
plt.tight_layout()
plt.show()

"""## Epoch Convergence Curve"""

import matplotlib.pyplot as plt

# Example: histories is a dict mapping strategy → list of accuracies per epoch
histories = {
    "Baseline":           [97.7, 98.0, 98.2, 98.2, 98.2],
    "Freeze All":         [83.0, 90.4, 92.4, 93.0, 93.2],
    "Freeze First 2":     [97.5, 97.9, 97.9, 98.1, 98.1],
    "Freeze First 4":     [96.6, 97.3, 97.5, 97.6, 97.7],
    "Alternating Freeze": [97.4, 97.9, 98.0, 98.1, 98.2],
}

plt.figure(figsize=(8,4))
for strat, accs in histories.items():
    plt.plot(range(1, len(accs)+1), accs, marker='o', label=strat)
plt.xlabel("Epoch")
plt.ylabel("Dev Accuracy")
plt.title("Convergence Curves by Freezing Strategy (Naija)")
plt.legend()
plt.grid(True, linestyle='--', alpha=0.5)
plt.tight_layout()
plt.show()

"""## Accuracy vs Model Size Trade-off"""

import matplotlib.pyplot as plt
import seaborn as sns

# Example data — replace with your actual numbers
param_counts = {
    "Baseline":           135,
    "Freeze All":           92,
    "Freeze First 2":       121,
    "Freeze First 4":       106,
    "Alternating Freeze":   113,
}
accuracies = {
    "Baseline":           98.2,
    "Freeze All":          93.2,
    "Freeze First 2":      98.1,
    "Freeze First 4":      97.7,
    "Alternating Freeze":  98.2,
}

# Create a consistent color palette
palette = sns.color_palette("Dark2", n_colors=len(param_counts))

plt.figure(figsize=(8, 4))
for (strategy, count), color in zip(param_counts.items(), palette):
    plt.scatter(count, accuracies[strategy], s=100, color=color, label=strategy)

plt.xlabel("Trainable Parameters (Millions)")
plt.ylabel("Eval Accuracy (%)")
plt.title("Accuracy vs. Model Size by Freezing Strategy (Naija)")
plt.grid(True, linestyle='--', alpha=0.5)

# Add legend instead of inline labels
plt.legend(title="Strategy", bbox_to_anchor=(1.05, 1), loc='upper left')

plt.tight_layout()
plt.show()

"""## Training Time Saving"""

from matplotlib import pyplot as plt
import seaborn as sns
import pandas as pd

# Example training times - replace with your actual timing metrics
data = {
    "Strategy": ["Baseline", "Freeze All", "Freeze First 2", "Freeze First 4", "Alternating Freeze"],
    "Training Time (seconds)": [388, 196, 249, 223, 236]
}
df_times = pd.DataFrame(data)

# Display the DataFrame to the user
display(df_times)

# Create horizontal bar chart with Dark2 palette
palette = sns.color_palette("Dark2", n_colors=len(df_times))
plt.figure(figsize=(8, 4))
ax = df_times.set_index('Strategy')['Training Time (seconds)'].plot(
    kind='barh',
    color=palette
)

# Annotate each bar with its training time value
for i, (strategy, time_val) in enumerate(zip(df_times['Strategy'], df_times['Training Time (seconds)'])):
    ax.text(time_val + 0.5, i, f"{time_val:.0f}", va='center')

# Remove top and right spines
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

plt.xlabel("Training Time (seconds)")
plt.title("Compute Savings by Freezing Strategy (Naija)")
plt.tight_layout()
plt.show()

"""## Result Summary"""

import pandas as pd

# 1) Raw experiment metrics
data = {
    "Strategy": [
        "Baseline",
        "Freeze All",
        "Freeze First 2",
        "Freeze First 4",
        "Alternating Freeze"
    ],
    "Dev Accuracy (%)": [
        98.2,  # Baseline
        93.2,  # Freeze All
        98.1,  # Freeze First 2
        97.7,  # Freeze First 4
        98.2   # Alternating Freeze
    ],
    "Trainable Params (M)": [
        134,  # Baseline
        92,   # Freeze All
        120,  # Freeze First 2
        106,  # Freeze First 4
        113   # Alternating Freeze
    ],
    "Training Time (s)": [
        388,  # Baseline
        196,  # Freeze All
        249,  # Freeze First 2
        223,  # Freeze First 4
        236   # Alternating Freeze
    ]
}

# 2) Build DataFrame
df = pd.DataFrame(data)

# 3) Compute savings (%) relative to baseline time
baseline_time = df.loc[df["Strategy"] == "Baseline", "Training Time (s)"].iloc[0]
df["Compute Savings (%)"] = (
    (baseline_time - df["Training Time (s)"]) / baseline_time * 100
).round(1)

# 4) Rearrange columns for readability
df = df[[
    "Strategy",
    "Dev Accuracy (%)",
    "Trainable Params (M)",
    "Training Time (s)",
    "Compute Savings (%)"
]]

# 5) Display as markdown table (or use display(df) in a notebook)
print(df.to_markdown(index=False))