import http.server
import socketserver
import cgi
import boto3

PORT = 80

#The bucket name
BUCKET = "ilay-bucket-devops" 

s3 = boto3.client("s3")


class UploadHandler(http.server.BaseHTTPRequestHandler):

    #Html code to upload a file
    def do_GET(self):
        html = b"""
        <h2 style="text-align: center; color: #4A90E2;">Upload file to S3 (Ilay-Bucket)</h2>
        <form enctype="multipart/form-data" method="post" style="max-width: 400px; margin: auto; padding: 20px; border: 1px solid #ccc; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); background-color: #f9f9f9;">
        <input type="file" name="file" style="width: 100%; padding: 10px; margin-bottom: 20px; border: 1px solid #ccc; border-radius: 5px;">
        <input type="submit" value="Upload" style="width: 100%; padding: 10px; background-color: #4A90E2; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px;">
        </form>
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html)

    # check the upload
    def do_POST(self):
        try:
            ctype, pdict = cgi.parse_header(self.headers.get("Content-Type"))
            if ctype != "multipart/form-data":
                self.send_error(400, "Invalid form")
                return

            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST"}
            )

            file_field = form["file"]
            filename = file_field.filename

            if not filename:
                self.send_error(400, "No file selected")
                return

            # Upload to S3
            s3.upload_fileobj(file_field.file, BUCKET, filename)

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Uploaded {filename} to S3".encode())

        except Exception as e:
            self.send_error(500, str(e))


with socketserver.TCPServer(("", PORT), UploadHandler) as httpd:
    print(f"Serving HTTP upload on port {PORT}")
    httpd.serve_forever()
