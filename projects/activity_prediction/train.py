import sys
sys.path.append('../../')
import pandas as pd
import torch
from activity_predictor import FFNN
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from Projects.activity_prediction.pytorchtools import CustomDataset, RepresentationDataset, train, evaluate_ensemble, plot_losses
import os
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.cluster import AgglomerativeClustering
import numpy as np
import argparse

# Hyper parameters (later all argparse)
parser = argparse.ArgumentParser(description='Hyperparameters')
parser.add_argument('--epochs', type=int, default=1000)
parser.add_argument('--batch_size', type=int, default=64)
parser.add_argument('--patience', type=int, default=100)
parser.add_argument('--num_layers', type=int, default=4)
parser.add_argument('--sequence_length', type=int, default=147)
parser.add_argument('--embedding_dimension', type=int, default=1280)
parser.add_argument('--nheads', type=int, default=8)
parser.add_argument('--d_model', type=int, default=1280)
parser.add_argument('--n_folds', type=int, default=4)
parser.add_argument('--output_size', type=int, default=1)
parser.add_argument('--hidden_layers', type=list, default=[1280, 1280])
parser.add_argument('--dropout_rate', type=float, default=0.2)
args = parser.parse_args()

num_layers = args.num_layers
nheads = args.nheads
d_model = args.d_model
epochs = args.epochs
batch_size = args.batch_size
patience = args.patience
sequence_length = args.sequence_length
embedding_dimension = args.embedding_dimension
n_folds = args.n_folds
output_size = args.output_size
hidden_layers = args.hidden_layers
dropout_rate = args.dropout_rate

save_path = 'checkpoints'
data_path = '../example_data/directed_evolution/GB1/GB1.csv'
train_log = 'train_log'
input_size = embedding_dimension
rep_layer = 33

if not os.path.exists(save_path):
    os.mkdir(save_path)

# pytorch device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# load data_tools and split into train and val. first naive split, normalize activity
df = pd.read_csv(data_path)
df['Data_normalized'] = (df['Data'] - df['Data'].min()) / (df['Data'].max() - df['Data'].min())

# Perform clustering based on sequence similarity (using Hamming distance)
def hamming_distance(s1, s2):
    return sum(el1 != el2 for el1, el2 in zip(s1, s2))

# Create a distance matrix using the Hamming distance
distance_matrix = pd.DataFrame([[hamming_distance(seq1, seq2) for seq1 in df['Sequence']] for seq2 in df['Sequence']])

# Perform Agglomerative Clustering
cluster = AgglomerativeClustering(n_clusters=None, affinity='precomputed', linkage='average', distance_threshold=5)
df['Cluster'] = cluster.fit_predict(distance_matrix)

# Split the data_tools into train/val and test datasets
train_val_df, test_df = train_test_split(df, test_size=0.1, random_state=42, stratify=df['Cluster'])

# Reset indices
train_val_df = train_val_df.reset_index(drop=True)
test_df = test_df.reset_index(drop=True)

# Create stratified splits
skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)

# Initialize variables to store metrics for each fold
all_train_losses = []
all_val_losses = []
all_val_rmse = []
all_val_pearson = []

# Perform 5-fold cross-validation
with open(os.path.join(save_path, train_log), 'w') as f:
    print(f'{n_folds}-fold cross validation:', file=f)

for fold, (train_idx, val_idx) in enumerate(skf.split(train_val_df, train_val_df['Cluster'])):
    # Create train and validation DataFrames for the current fold
    train_df = df.iloc[train_idx].drop(columns=['Cluster'])
    val_df = df.iloc[val_idx].drop(columns=['Cluster'])

    # Reset indices
    train_df = train_df.reset_index(drop=True)
    val_df = val_df.reset_index(drop=True)

    # Dataloaders
    train_set = RepresentationDataset(train_df)
    val_set = RepresentationDataset(val_df)
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=True)

    # Load activity predictor model
    model = FFNN(input_size, output_size, hidden_layers, dropout_rate)
    model.to(device)

    # Define the loss function and optimizer
    loss_fn = nn.MSELoss()
    optimizer = optim.Adam(model.parameters())

    fold_train_losses, fold_val_losses, fold_val_rmse, fold_val_pearson = train(model, train_loader, val_loader, loss_fn, optimizer, device, epochs, patience, save_path, fold, train_log)

    all_train_losses.append(fold_train_losses)
    all_val_losses.append(fold_val_losses)
    all_val_rmse.append(fold_val_rmse)
    all_val_pearson.append(fold_val_pearson)

# Calculate average metrics across all folds
avg_train_losses = np.mean(all_train_losses, axis=0)
avg_val_losses = np.mean(all_val_losses, axis=0)
avg_val_rmse = np.mean(all_val_rmse, axis=0)
avg_val_pearson = np.mean(all_val_pearson, axis=0)

plot_losses('ensemble_losses.png', all_train_losses, all_val_losses, n_folds)

# Create a test DataLoader
test_set = RepresentationDataset(test_df)
test_loader = DataLoader(test_set, batch_size=batch_size, shuffle=False)

# Load the best activity_prediction from each fold and store them in a list
ensemble_models = []
for fold in range(n_folds):
    model_path = os.path.join(save_path, f'activity_model_{fold + 1}')
    model = FFNN(input_size, output_size, hidden_layers, dropout_rate)
    model.load_state_dict(torch.load(model_path))
    model.to(device)
    model.eval()
    ensemble_models.append(model)

# Evaluate the ensemble on the test dataset
test_rmse, test_pearson = evaluate_ensemble(ensemble_models, test_loader, device)
with open('results', 'w') as f:
    print('Test RMSE:', test_rmse, file=f)
    print('Test Pearson:', test_pearson, file=f)