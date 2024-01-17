# This source code is part of the proteusAI package and is distributed
# under the MIT License.

__name__ = "proteusAI"
__author__ = "Jonathan Funk"

from typing import Union
import inspect
import os
import warnings
import sys
current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.join(current_path, '..')
sys.path.append(root_path)
from proteusAI.ml_tools.esm_tools import *
import hashlib

class Protein:
    """
    The protein object contains information about a single protein,
    such as its sequence, name, and its mathematical representations.
    
    Attributes:
        name (str): Name/id of the protein.
        seq (str): Protein sequence.
        rep (list): List of available representations.
        rep_path (str): Path to representations directory.
    """

    def __init__(self, name: Union[str, None] = None, seq: Union[str, None] = None, reps: Union[list, tuple] = [], rep_path: Union[str, None] = None, y = None):
        """
        Initialize a new protein object.

        Args:
            name (str): Name/id of the protein.
            seq (str): Protein sequence.
            reps (list): List of available representations.
            rep_path (str): Path to representations directory. Default './rep/'.
            y (float, int, str): Label for the protein.
        """

        # assertions and checks
        assert isinstance(name, (str, type(None)))
        assert isinstance(seq, (str, type(None)))
        assert isinstance(reps, (list, tuple))
        assert isinstance(rep_path, (str, type(None)))

        self.name = name
        self.seq = seq
        self.reps = list(reps)
        self.y = y
        
        # If path is not provided, use the directory of the calling script
        if rep_path is None:
            caller_path = os.path.dirname(self.get_caller_path())
            self.path = os.path.join(caller_path, 'rep')
        else:
            assert isinstance(rep_path, str)
            self.path = rep_path

    def get_caller_path(self):
        """Returns the path of the script that called the function."""
        caller_frame = inspect.stack()[1]
        caller_path = caller_frame[1]
        return os.path.abspath(caller_path)

    def __str__(self):
        return f"proteusAI.Protein():\n____________________\nname\t: {self.name}\nseq\t: {self.seq}\nrep\t: {self.reps}\ny\t{self.y}"
    
    __repr__ = __str__

    ### Class methods ###
    @classmethod
    def load_fasta(cls, file: str):
        """
        Load protein sequence from a FASTA file.

        Args:
            file (str): Path to the FASTA file.
        """
        sequences = []
        headers = []
        header = None
        seq = []

        with open(file, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('>'):
                    if header:
                        sequences.append(''.join(seq))
                        seq = []
                    header = line[1:]
                    headers.append(header)
                else:
                    seq.append(line)

            if seq:
                sequences.append(''.join(seq))

        if not headers:
            raise ValueError(f"The file {file} is not in FASTA format or is empty.")
        
        if len(headers) > 1:
            warnings.warn("The provided FASTA file contains multiple entries. Using only the first entry.")

        # Set the header as self.name
        name = headers[0].strip()  # remove potential leading spaces

        # Store the first sequence in self.seq
        seq = sequences[0]

        # Create and return a new Protein instance
        return cls(name=name, seq=seq)
    
    ### Zero-shot prediction ###
    def zs_prediction(self, model='esm2', batch_size=1):
        seq = self.seq

        # check scores for this protein and model have already been computed
        seq_hash = hashlib.md5((seq+model).encode()).hexdigest()

        project_path = self.path
        dest = os.path.join(project_path, "zero_shot", model, seq_hash)

        # Check if results already exist
        if os.path.exists(dest):
            print(f"Results already computed. Loading from {dest}")
            p = torch.load(os.path.join(dest, "prob_dist.pt"))
            mmp = torch.load(os.path.join(dest, "masked_marginal_probability.pt"))
            entropy = torch.load(os.path.join(dest, "per_position_entropy.pt"))
            logits = torch.load(os.path.join(dest, "masked_logits.pt"))
            df = pd.read_csv(os.path.join(dest, "zs_scores.csv"))
        else:
            # Perform computation if results do not exist
            print("Computing logits")
            logits, alphabet = get_mutant_logits(seq, batch_size=batch_size, model=model)

            # Calculations
            p = get_probability_distribution(logits)
            mmp = masked_marginal_probability(p, seq, alphabet)
            entropy = per_position_entropy(p)

            # Create directory if it doesn't exist
            if not os.path.exists(dest):
                os.makedirs(dest)
                print(f"Directory created at {dest}")

            # Save tensors
            torch.save(p, os.path.join(dest, "prob_dist.pt"))
            torch.save(mmp, os.path.join(dest, "masked_marginal_probability.pt"))
            torch.save(entropy, os.path.join(dest, "per_position_entropy.pt"))
            torch.save(logits, os.path.join(dest, "masked_logits.pt"))

            df = zs_to_csv(seq, alphabet, p, mmp, entropy, os.path.join(dest, "zs_scores.csv"))

        return df

    
    ### getters and setters ###
    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        if not isinstance(value, str) and value is not None:
            raise TypeError(f"Expected 'name' to be of type 'str', but got '{type(value).__name__}'")
        self._name = value

    # For seq
    @property
    def seq(self):
        return self._seq

    @seq.setter
    def seq(self, value):
        if not isinstance(value, str) and value is not None:
            raise TypeError(f"Expected 'seq' to be of type 'str', but got '{type(value).__name__}'")
        self._seq = value

    # For rep
    @property
    def reps(self):
        return self._reps

    @reps.setter
    def reps(self, value):
        if not isinstance(value, (list, tuple)) and value is not None:
            raise TypeError(f"Expected 'rep' to be of type 'list' or 'tuple', but got '{type(value).__name__}'")
        self._reps = list(value)

    # For path
    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, value):
        if not isinstance(value, str) and value is not None:
            raise TypeError(f"Expected 'path' to be of type 'str', but got '{type(value).__name__}'")
        self._path = value

    # For y
    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, value):
        if not isinstance(value, (str, int, float)) and value is not None:
            raise TypeError(f"Expected 'rep' to be of type 'int', 'float', or 'str', but got '{type(value).__name__}'")
        self._y = value