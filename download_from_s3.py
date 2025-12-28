import boto3

BUCKET = "ilay-bucket-devops"      
KEY = "try.py"                     
LOCAL_PATH = "/home/ubuntu/try.py" 

s3 = boto3.client("s3")

def download():
    try:
        s3.download_file(BUCKET, KEY, LOCAL_PATH)
        print(f"Downloaded {KEY} -> {LOCAL_PATH}")
    except Exception as e:
        print("Download failed:", e)

if __name__ == "__main__":
    download()
