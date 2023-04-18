import sys
sys.path.append('../')
import pandas as pd
import torch
from torch import nn
import torch.optim as optim
from torch.utils.data import DataLoader
from models.pytorchtools import CustomDataset, train, evaluate_ensemble, create_optimization_report
import os
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.cluster import AgglomerativeClustering
import numpy as np
import argparse
from activity_predictor import AttentionModel
import optuna
import json

# Hyper parameters (later all argparse)
parser = argparse.ArgumentParser(description='Hyperparameters')
parser.add_argument('--epochs', type=int, default=10)
parser.add_argument('--batch_size', type=int, default=26)
parser.add_argument('--nhead', type=int, default=8)
parser.add_argument('--num_layers', type=int, default=3)
parser.add_argument('--d_model', type=int, default=512)
parser.add_argument('--patience', type=int, default=90)
args = parser.parse_args()

epochs = args.epochs
batch_size = args.batch_size
nhead = args.nhead
num_layers = args.num_layers
d_model = args.d_model
patience = args.patience

save_path = 'checkpoints'
data_path = '../example_data/directed_evolution/GB1/GB1.csv'
train_log = 'train_log'
sequence_length = 147
embedding_dimension = 1280
n_folds = 1
output_size = 1

if not os.path.exists(save_path):
    os.mkdir(save_path)

# pytorch device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def save_best_trial(study, trial):
    # Check if there are any completed trials.
    if len([t for t in study.get_trials() if t.state == optuna.trial.TrialState.COMPLETE]) == 0:
        return

    if study.best_trial == trial:
        best_hyperparams = study.best_trial.params
        with open("best_hyperparams.json", "w") as f:
            json.dump(best_hyperparams, f)

def objective(trial):
    # Hyperparameters to optimize
    epochs = trial.suggest_int("epochs", 150, 500)
    batch_size = trial.suggest_categorical("batch_size", [16, 32, 64])
    num_layers = trial.suggest_int("num_layers", 1, 4)
    d_model = trial.suggest_int("d_model", 128, 1024, 64)
    beta1 = trial.suggest_float("beta1", 0.8, 0.999)
    beta2 = trial.suggest_float("beta2", 0.9, 0.9999)
    eps = trial.suggest_float("eps", 1e-9, 1e-7, log=True)
    dropout_rate = trial.suggest_float("dropout_rate", 0.1, 0.5)

    # Ensure nhead is a factor of d_model
    possible_nhead_values = [i for i in range(1, d_model+1) if d_model % i == 0]

    # Suggest a divisor index and calculate nhead based on the index and d_model
    divisor_idx = trial.suggest_int("divisor_idx", 0, len(possible_nhead_values) - 1)
    nhead = possible_nhead_values[divisor_idx]

    learning_rate = trial.suggest_float("learning_rate", 1e-5, 1e-2, log=True)

    # Call the train_and_evaluate function with suggested hyperparameters
    avg_val_loss = train_and_evaluate(epochs, batch_size, num_layers, nhead, d_model, patience, learning_rate, beta1, beta2, eps, dropout_rate)

    return avg_val_loss


# Perform clustering based on sequence similarity (using Hamming distance)
def hamming_distance(s1, s2):
    return sum(el1 != el2 for el1, el2 in zip(s1, s2))

# load data and split into train and val. first naive split, normalize activity
df = pd.read_csv(data_path)
df['Data_normalized'] = (df['Data'] - df['Data'].min()) / (df['Data'].max() - df['Data'].min())

# Create a distance matrix using the Hamming distance
distance_matrix = pd.DataFrame(
    [[hamming_distance(seq1, seq2) for seq1 in df['Sequence']] for seq2 in df['Sequence']])

# Perform Agglomerative Clustering
cluster = AgglomerativeClustering(n_clusters=None, affinity='precomputed', linkage='average', distance_threshold=5)
df['Cluster'] = cluster.fit_predict(distance_matrix)

# Split the data into train/val and test datasets
train_val_df, test_df = train_test_split(df, test_size=0.1, random_state=42, stratify=df['Cluster'])

# Reset indices
train_val_df = train_val_df.reset_index(drop=True)
test_df = test_df.reset_index(drop=True)

def train_and_evaluate(epochs, batch_size, num_layers, nhead, d_model, patience, learning_rate, beta1, beta2, eps, dropout_rate):
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
        print(f'epochs: {epochs}, batch_size : {batch_size}, num_layers : {num_layers}, nhead : {nhead}, d_model : {d_model}', file=f)
        print(f'learning_rate : {learning_rate}, beta1 : {beta1}, beta2 : {beta2}, eps : {eps}, dropout_rate : {dropout_rate}', file=f)

    for fold, (train_idx, val_idx) in enumerate(skf.split(train_val_df, train_val_df['Cluster'])):
        # Create train and validation DataFrames for the current fold
        train_df = df.iloc[train_idx].drop(columns=['Cluster'])
        val_df = df.iloc[val_idx].drop(columns=['Cluster'])

        # Reset indices
        train_df = train_df.reset_index(drop=True)
        val_df = val_df.reset_index(drop=True)

        # Dataloaders
        train_set = CustomDataset(train_df)
        val_set = CustomDataset(val_df)
        train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=True)

        # Load activity predictor model
        model = AttentionModel(embedding_dimension, sequence_length, d_model, nhead, num_layers, dropout_rate)
        model.to(device)

        # Define the loss function and optimizer
        loss_fn = nn.MSELoss()
        optimizer = optim.Adam(model.parameters(), lr=learning_rate, betas=(beta1, beta2), eps=eps)

        fold_train_losses, fold_val_losses, fold_val_rmse, fold_val_pearson = train(model, train_loader, val_loader,
                                                                                    loss_fn, optimizer, device, epochs,
                                                                                    patience, save_path, fold,
                                                                                    train_log)

        all_train_losses.append(fold_train_losses)
        all_val_losses.append(fold_val_losses)
        all_val_rmse.append(fold_val_rmse)
        all_val_pearson.append(fold_val_pearson)

    # Pad the arrays with NaNs so that they have the same length
    # padded_train_losses = pad_arrays(all_train_losses)
    # padded_val_losses = pad_arrays(all_val_losses)
    # padded_val_rmse = pad_arrays(all_val_rmse)
    # padded_val_pearson = pad_arrays(all_val_pearson)

    # Calculate average metrics across all folds
    # avg_train_losses = np.nanmean(padded_train_losses, axis=0)
    # avg_val_losses = np.nanmean(padded_val_losses, axis=0)
    # avg_val_rmse = np.nanmean(padded_val_rmse, axis=0)
    # avg_val_pearson = np.nanmean(padded_val_pearson, axis=0)

    # Calculate the minimum validation loss for each fold
    min_val_losses = [np.min(fold_val_losses) for fold_val_losses in all_val_losses]

    # Calculate the average of the minimum validation losses
    avg_min_val_loss = np.mean(min_val_losses)

    return avg_min_val_loss

# Create a study and run optimization
study = optuna.create_study(direction="minimize")
study.optimize(objective, n_trials=100, callbacks=[save_best_trial])
create_optimization_report(study)

# print the best hyperparameters and the corresponding best value
with open('hyperoptimization','w') as f:
    print(f"Best trial: {study.best_trial.number}", file=f)
    print(f"Best value (average validation loss): {study.best_value}", file=f)
    print("Best hyperparameters:", file=f)
    for key, value in study.best_trial.params.items():
        print(f"{key}: {value}", file=f)

# train the final model using the best hyperparameters and evaluate on the test set
best_epochs = study.best_trial.params["epochs"]
best_batch_size = study.best_trial.params["batch_size"]
best_num_layers = study.best_trial.params[f"num_layers"]
best_learning_rate = study.best_trial.params["learning_rate"]
best_beta1 = study.best_trial.params["beta1"]
best_beta2 = study.best_trial.params["beta2"]
best_eps = study.best_trial.params["eps"]
best_dropout_rate = study.best_trial.params["dropout_rate"]
best_d_model = study.best_trial.params["d_model"]

# Get the best divisor index and calculate the optimal number of heads
best_divisor_idx = study.best_trial.params["divisor_idx"]
possible_nhead_values = [i for i in range(1, d_model + 1) if d_model % i == 0]
best_nhead = possible_nhead_values[best_divisor_idx]

# 5 fold for evaluation
n_folds = 5
avg_val_loss = train_and_evaluate(best_epochs, best_batch_size, best_num_layers, best_nhead, best_d_model, patience, best_learning_rate, best_beta1, best_beta2, best_eps, best_dropout_rate)

# load the best models from each fold and store them in a list
ensemble_models = []
for fold in range(n_folds):
    model_path = os.path.join(save_path, f'activity_model_{fold + 1}')
    model = AttentionModel(embedding_dimension, sequence_length, best_d_model, best_nhead, best_num_layers, best_dropout_rate)
    model.load_state_dict(torch.load(model_path))
    model.to(device)
    model.eval()
    ensemble_models.append(model)

# evaluate the ensemble on the test dataset
test_set = CustomDataset(test_df)
test_loader = DataLoader(test_set, batch_size=batch_size, shuffle=True)

test_rmse, test_pearson = evaluate_ensemble(ensemble_models, test_loader, device)
with open('results', 'w') as f:
    print('Test RMSE:', test_rmse, file=f)
    print('Test Pearson:', test_pearson, file=f)