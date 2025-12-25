import boto3

BUCKET = "ilay-bucket-devops"      #The name of the bucket
KEY = "try.py"                     #The name of the file in S3
LOCAL_PATH = "/home/ubuntu/try.py" #Path to save

s3 = boto3.client("s3")

def download():
    try:
        s3.download_file(BUCKET, KEY, LOCAL_PATH)
        print(f"Downloaded {KEY} -> {LOCAL_PATH}")
    except Exception as e:
        print("Download failed:", e)

if __name__ == "__main__":
    download()
