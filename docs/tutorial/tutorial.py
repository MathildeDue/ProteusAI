# %% [markdown]
# # Tutorial

# %% 
import proteusAI as pai
pai.__version__

# load data from csv or excel: x should be sequences, y should be labels, y_type class or num
library = pai.Library(user='guest', source='demo/demo_data/master_dataset.csv', seqs_col='binder_seq', y_col='pae_interaction_*', 
                    y_type='num', names_col='binder_name')


# compute and save ESM-2 representations at example_lib/representations/esm2
#library.compute(method='esm2', batch_size=10)


# define a model
model = pai.Model(library=library, k_folds=5, model_type='rf', x='blosum62', seed=42)


# train model
_ = model.train()

# search for new mutants
out = model.search()



# print predictions
print(out.to_csv('test.csv'), index=False)
#print(out['df'])
