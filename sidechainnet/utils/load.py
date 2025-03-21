"""Implements SidechainNet loading functionality."""

import pickle
import os

import requests
import tqdm

from sidechainnet.create import format_sidechainnet_path
from sidechainnet.dataloaders.collate import prepare_dataloaders


def _get_local_sidechainnet_path(casp_version, thinning, scn_dir):
    """Return local path to SidechainNet file iff it exists, else returns None."""
    filepath = os.path.join(scn_dir, format_sidechainnet_path(casp_version, thinning))
    if os.path.isfile(filepath):
        return filepath
    else:
        return None


def _copyfileobj(fsrc, fdst, length=0, chunks=0.):
    """Copy data from file-like object fsrc to file-like object fdst.

    Modified from shutil.copyfileobj to include a progress bar with tqdm.
    """
    # Localize variable access to minimize overhead.
    if not length:
        length = 64 * 1024
    fsrc_read = fsrc.read
    fdst_write = fdst.write
    if chunks:
        pbar = tqdm.tqdm(total=int(chunks),
                         desc='Downloading file chunks (estimated)',
                         unit='chunk',
                         dynamic_ncols=True)
    while True:
        buf = fsrc_read(length)
        if not buf:
            break
        fdst_write(buf)
        if chunks:
            pbar.update()


def _download(url, file_name):
    """Download a file at a given URL to a specified local file_name with shutil."""
    # File length can only be approximated from the resulting GET, unfortunately
    r = requests.get(url, stream=True)
    if 'Content-Length' in r.headers:
        file_len = int(r.headers['Content-Length'])
    elif 'X-Original-Content-Length' in r.headers:
        file_len = int(r.headers['X-Original-Content-Length'])
    else:
        file_len = 0
    r.raw.decode_content = True
    with open(file_name, 'wb') as f:
        _copyfileobj(r.raw, f, chunks=(file_len / (64. * 1024)))
    r.close()

    return file_name


def _download_sidechainnet(casp_version, thinning, scn_dir):
    """Download the specified version of Sidechainnet."""
    # Prepare destination paths for downloading
    if format_sidechainnet_path(casp_version, thinning) not in BOXURLS:
        raise FileNotFoundError(
            "The requested file is currently unavailable. Please check back later.")
    outfile_path = os.path.join(scn_dir, format_sidechainnet_path(casp_version, thinning))
    os.makedirs(os.path.dirname(outfile_path), exist_ok=True)
    print("Downloading from", BOXURLS[format_sidechainnet_path(casp_version, thinning)])

    # Use a data-agnostic tool for downloading URL data from Box to a specified local file
    _download(BOXURLS[format_sidechainnet_path(casp_version, thinning)], outfile_path)
    print(f"Downloaded SidechainNet to {outfile_path}.")

    return outfile_path


def _load_dict(local_path):
    """Load a pickled dictionary."""
    with open(local_path, "rb") as f:
        d = pickle.load(f)
    print(f"SidechainNet was loaded from {local_path}.")
    return d


def load(casp_version=12,
         thinning=30,
         scn_dir="./sidechainnet_data",
         force_download=False,
         with_pytorch=None,
         aggregate_model_input=True,
         collate_fn=None,
         batch_size=32,
         return_masks=False,
         seq_as_onehot=None,
         dynamic_batching=True,
         num_workers=2,
         optimize_for_cpu_parallelism=False,
         train_eval_downsample=.2):
    #: Okay
    """Load and return the specified SidechainNet dataset as a dictionary or DataLoaders.

    This function flexibly allows the user to load SidechainNet in a format that is most
    convenient to them. The user can specify which version and "thinning" of the dataset
    to load, and whether or not they would like the data prepared as a PyTorch DataLoader
    (with_pytorch='dataloaders') for easy access for model training with PyTorch. Several
    arguments are also available to allow the user to specify how the data should be
    loaded and batched when provided as DataLoaders (aggregate_model_input, collate_fn,
    batch_size, return_masks, seq_as_one_hot, dynamic_batching, num_workers,
    optimize_for_cpu_parallelism, and train_eval_downsample.)

    Args:
        casp_version (int, optional): CASP version to load (7-12). Defaults to 12.
        thinning (int, optional): ProteinNet/SidechainNet "thinning" to load. A thinning
            represents the minimum sequence similarity each protein sequence must have to
            all other sequences in the same thinning. The 100 thinning contains all of the
            protein entries in SidechainNet, while the 30 thinning has a much smaller
            amount. Defaults to 30.
        scn_dir (str, optional): Path where SidechainNet data will be stored locally.
            Defaults to "./sidechainnet_data".
        force_download (bool, optional): If true, download SidechainNet data from the web
            even if it already exists locally. Defaults to False.
        with_pytorch (str, optional): If equal to 'dataloaders', returns a dictionary
            mapping dataset splits (e.g. 'train', 'test', 'valid-X') to PyTorch
            DataLoaders for data batching and model training. Defaults to None.
        aggregate_model_input (bool, optional): If True, the batches in the DataLoader
            contain a single entry for all of the SidechainNet data that is favored for
            use in a predictive model (sequences and PSSMs). This entry is a single
            Tensor. However, if False, when batching these entries are returned
            separately. See method description. Defaults to True.
        collate_fn (Callable, optional): A collating function. Defaults to None. See:
            https://pytorch.org/docs/stable/data.html#dataloader-collate-fn.
        batch_size (int, optional): Batch size to be used with PyTorch DataLoaders. Note
            that if dynamic_batching is True, then the size of the batch will not
            necessarily be equal to this number (though, on average, it will be close
            to this number). Only applicable when with_pytorch='dataloaders' is provided.
            Defaults to 32.
        return_masks (bool, optional): If True, when batching, returns sequence masks as a
            Tensor of 1s and 0s (with 0s representing missing residues). In the batch,
            masks are always provided in the tuple following the model input or sequences.
            For example, with aggregated model input and return_masks=True, batching
            yields tuples of (protein_ids, model_input, masks, angles, coordinates). If
            aggregate_model_input=False, and return_masks=True, batching yields tuples of
            (protein_ids, sequences, masks, PSSMs, angles, coordinates). Defaults to
            False.
        seq_as_onehot (bool, optional): By default, the None value of this argument causes
            sequence data to be represented as one-hot vectors (L x 20) when batching and
            aggregate_model_input=True or to be represented as integer sequences (shape L,
            values 0 through 21 with 21 being a pad character). The user may override this
            option with seq_as_onehot=False only when aggregate_model_input=False.
        dynamic_batching (bool, optional): If True, uses a dynamic batch size when
            training that increases when the proteins within a batch have short sequences
            or decreases when the proteins within a batch have long sequences. Behind the
            scenes, this function bins the sequences in the training Dataset/DataLoader
            by their length. For every batch, it selects a bin at random (with a
            probability proportional to the number of proteins within that bin), and then
            selects N proteins within that batch, where:
                N = (batch_size * average_length_in_dataset)/max_length_in_bin.
            This means that, on average, each batch will have about the same number of
            amino acids. If False, uses a constant value (specified by batch_size) for
            batch size.
        num_workers (int, optional): Number of workers passed to DataLoaders. Defaults to
            2. See the description of workers in the PyTorch documentation:
            https://pytorch.org/docs/stable/data.html#single-and-multi-process-data-loading.
        optimize_for_cpu_parallelism (bool, optional): If True, ensure that the size of
            each batch is a multiple of the number of available CPU cores. Defaults to
            False.
        train_eval_downsample (float, optional): The fraction of the training set to
            include in the 'train-eval' DataLoader/Dataset that is returned. This is
            included so that, instead of evaluating the entire training set during each
            epoch of training (which can be expensive), we can first downsample the
            training set at the start of training, and use that downsampled dataset during
            the whole of model training. Defaults to .2.

    Returns:
        A Python dictionary that maps data splits ('train', 'test', 'train-eval',
        'valid-X') to either more dictionaries containing protein data ('seq', 'ang',
        'crd', etc.) or to PyTorch DataLoaders that can be used for training. See below.

        Option 1 (Python dictionary):
            By default, the function returns a dictionary that is organized by training/
            validation/testing splits. For example, the following code loads CASP 12 with
            the 30% thinning option:

                >>> import sidechainnet as scn
                >>> data = scn.load(12, 30)

            `data` is a Python dictionary with the following structure:

                data = {"train": {"seq": [seq1, seq2, ...],  # Sequences
                        "ang": [ang1, ang2, ...],  # Angles
                        "crd": [crd1, crd2, ...],  # Coordinates
                        "evo": [evo1, evo2, ...],  # PSSMs and Information Content
                        "ids": [id1, id2,   ...],  # Corresponding ProteinNet IDs
                        },
                        "valid-10": {...},
                            ...
                        "valid-90": {...},
                        "test":     {...},
                        "settings": {...},
                        "description" : "SidechainNet for CASP 12."
                        "date": "September 20, 2020"
                        }

        Option 2 (PyTorch DataLoaders):
            Alternatively, if the user provides `with_pytorch='dataloaders'`, `load` will
            return a dictionary mapping dataset "splits" (e.g. 'train', 'test', 'valid-X'
            where 'X' is one of the validation set splits defined by ProteinNet/
            SidechainNet).

            By default, the provided `DataLoader`s use a custom batching method that
            randomly generates batches of proteins of similar length for faster training.
            The probability of selecting small-length batches is decreased so that each
            protein in SidechainNet is included in a batch with equal probability. See
            `dynamic_batching` and  `collate_fn` arguments for more information on
            modifying this behavior. In the example below, `model_input` is a collated
            Tensor containing sequence and PSSM information.

                >>> dataloaders = scn.load(casp_version=12, with_pytorch="dataloaders")
                >>> dataloaders.keys()
                ['train', 'train_eval', 'valid-10', ..., 'valid-90', 'test']
                >>> for (protein_id, protein_seqs, model_input, true_angles,
                        true_coords) in dataloaders['train']:
                ....    predicted_angles = model(model_input)
                ....    predicted_coords = angles_to_coordinates(predicted_angles)
                ....    loss = compute_loss(predicted_angles, predicted_coords,
                                            true_angles, true_coords)
                ....    ...

            We have also made it possible to access the protein sequence and PSSM data
            directly when training by adding `aggregate_model_input=False` to `scn.load`.

                >>> dataloaders = scn.load(casp_version=12, with_pytorch="dataloaders",
                                        aggregate_model_input=False)
                >>> for (protein_id, sequence, pssm, true_angles,
                        true_coords) in dataloaders['train']:
                ....    prediction = model(sequence, pssm)
                ....    ...
    """
    local_path = _get_local_sidechainnet_path(casp_version, thinning, scn_dir)
    if not local_path:
        print(f"SidechainNet{(casp_version, thinning)} was not found in {scn_dir}.")
    if not local_path or force_download:
        # Download SidechainNet if it does not exist locally, or if requested
        local_path = _download_sidechainnet(casp_version, thinning, scn_dir)

    scn_dict = _load_dict(local_path)

    # By default, the load function returns a dictionary
    if not with_pytorch:
        return scn_dict

    if with_pytorch == "dataloaders":
        return prepare_dataloaders(
            scn_dict,
            aggregate_model_input=aggregate_model_input,
            collate_fn=collate_fn,
            batch_size=batch_size,
            num_workers=num_workers,
            return_masks=return_masks,
            seq_as_onehot=seq_as_onehot,
            dynamic_batching=dynamic_batching,
            optimize_for_cpu_parallelism=optimize_for_cpu_parallelism,
            train_eval_downsample=train_eval_downsample)

    return


# TODO: Finish uploading files to Box for distribution
BOXURLS = {
    # CASP 12
    "sidechainnet_casp12_30.pkl":
        "https://pitt.box.com/shared/static/sjnecyqfm8hkqf0nk5yz1cf3ct4dygyf.pkl",
    "sidechainnet_casp12_50.pkl":
        "https://pitt.box.com/shared/static/h2sdnmxgobh9duamfzqvinjbx0tswn1i.pkl",
    "sidechainnet_casp12_70.pkl":
        "https://pitt.box.com/shared/static/7ikrp46bej1wylieqjpw76ceabcnc7r4.pkl",
    "sidechainnet_casp12_90.pkl":
        "https://pitt.box.com/shared/static/yn5ucsxwo9bp01yp23jltseg4j8sb3f8.pkl",
    "sidechainnet_casp12_95.pkl":
        "https://pitt.box.com/shared/static/k3fr29s5dyckj6f535silvqab6ikai43.pkl",
    "sidechainnet_casp12_100.pkl":
        "https://pitt.box.com/shared/static/52ggdgl60optmp57b5mcwocv4cabwmbv.pkl",

    # CASP 11
    "sidechainnet_casp11_30.pkl":
        "",
    "sidechainnet_casp11_50.pkl":
        "",
    "sidechainnet_casp11_70.pkl":
        "",
    "sidechainnet_casp11_90.pkl":
        "",
    "sidechainnet_casp11_95.pkl":
        "",
    "sidechainnet_casp11_100.pkl":
        "",

    # CASP 10
    "sidechainnet_casp10_30.pkl":
        "",
    "sidechainnet_casp10_50.pkl":
        "",
    "sidechainnet_casp10_70.pkl":
        "",
    "sidechainnet_casp10_90.pkl":
        "",
    "sidechainnet_casp10_95.pkl":
        "",
    "sidechainnet_casp10_100.pkl":
        "",

    # CASP 9
    "sidechainnet_casp9_30.pkl":
        "",
    "sidechainnet_casp9_50.pkl":
        "",
    "sidechainnet_casp9_70.pkl":
        "",
    "sidechainnet_casp9_90.pkl":
        "",
    "sidechainnet_casp9_95.pkl":
        "",
    "sidechainnet_casp9_100.pkl":
        "",

    # CASP 8
    "sidechainnet_casp8_30.pkl":
        "",
    "sidechainnet_casp8_50.pkl":
        "",
    "sidechainnet_casp8_70.pkl":
        "",
    "sidechainnet_casp8_90.pkl":
        "",
    "sidechainnet_casp8_95.pkl":
        "",
    "sidechainnet_casp8_100.pkl":
        "",

    # CASP 7
    "sidechainnet_casp7_30.pkl":
        "",
    "sidechainnet_casp7_50.pkl":
        "",
    "sidechainnet_casp7_70.pkl":
        "",
    "sidechainnet_casp7_90.pkl":
        "",
    "sidechainnet_casp7_95.pkl":
        "",
    "sidechainnet_casp7_100.pkl":
        "",

    # Other
    "debug.pkl":
        "https://pitt.box.com/shared/static/t1t9ahdhgv5h8937rdani9ihp34gs7bu.pkl"
}
