# Local datasets — never committed

Large third-party datasets live here and are gitignored. Nothing in this
directory is required for the project to run: every headline result in the repo
comes from the seeded Razorpay test-mode corpus, and the files here only feed
the additional real-data evaluation.

## ieee/ — IEEE-CIS Fraud Detection

Download from https://www.kaggle.com/c/ieee-fraud-detection/data
(free account, accept the competition rules), and place two files here:

    backend/data/ieee/train_transaction.csv    ~683 MB   REQUIRED
    backend/data/ieee/train_identity.csv       ~26 MB    REQUIRED

Do **not** bother with `test_transaction.csv` or `test_identity.csv`. The test
split's `isFraud` column is withheld for the competition, so nothing can be
measured against it.

`train_identity.csv` is small and easy to skip, but it carries `DeviceInfo` —
the only device-like identifier in the dataset. Without it the graph can only
be built from card and address columns, and a third of the model is lost.

### What this dataset can and cannot show

It labels **transactions** as fraudulent, not **accounts** as ring members. So
ring recall is not measurable here and must never be reported. What is
measurable is fraud-rate lift: whether clusters the detector flags carry a
materially higher fraud rate than the population base rate. That is a real
result on data this project did not generate, and it is reported as lift.

### Licence

The dataset is provided by IEEE-CIS and Vesta under the competition rules you
accept on download. It is not redistributed here.
