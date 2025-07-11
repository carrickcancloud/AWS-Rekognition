import boto3
import os
from botocore.exceptions import ClientError
from typing import List, Dict, Any

# Print all environment variables from GitHub Actions
print("All Environment Variables:")
for key, value in os.environ.items():
    print(f"{key}: {value}")

# Constants for AWS Rekognition analysis
REGION = os.getenv('AWS_REGION') # Passed from GitHub Actions workflows
BUCKET = os.getenv('S3_BUCKET') # Passed from GitHub Actions workflows
DYNAMODB = os.getenv('DYNAMODB_TABLE') # Passed from GitHub Actions workflows
PREFIX = 'rekognition-input/'
IMAGES_FOLDER = 'images/'
BRANCH = os.getenv('GITHUB_REF', 'refs/heads/main').split('/')[-1] # Extract branch name from GitHub

# Initialize boto3 clients
s3_client = boto3.client('s3')
rekognition_client = boto3.client('rekognition', region_name=REGION)
dynamodb_client = boto3.client('dynamodb', region_name=REGION)

def upload_image_to_s3(image_path: str) -> bool:
    """Uploads an image to the specified S3 bucket.

    Args:
        image_path (str): The path of the image to upload.

    Returns:
        bool: True if the upload was successful, False otherwise.
    """
    try:
        s3_client.upload_file(
            Filename=image_path,
            Bucket=BUCKET,
            Key=f"{PREFIX}{os.path.basename(image_path)}"
        )
        return True
    except ClientError as e:
        print(f"Error uploading {image_path} to S3: {e}")
        return False

def analyze_image_using_rekognition(image_name: str) -> tuple[List[Dict[str, Any]], Any]:
    """Analyzes an image using AWS Rekognition.

    Args:
        image_name (str): The name of the image to analyze.

    Returns:
        List[Dict[str, Any]]: A list of labels and their confidence scores.
    """
    try:
        response = rekognition_client.detect_labels(
            Image={
                'S3Object': {
                    'Bucket': BUCKET,
                    'Name': f"{PREFIX}{image_name}"
                }
            }
        )
        return response['Labels'], response  # Return both labels and the response
    except ClientError as e:
        print(f"Error analyzing {image_name} with Rekognition: {e}")
        return [], None  # Return empty labels and None for response

def store_results_in_dynamodb(image_name: str, labels: List[Dict[str, Any]], timestamp: str) -> bool:
    """Stores the analysis results in DynamoDB.

    Args:
        image_name (str): The name of the image.
        labels (List[Dict[str, Any]]): The labels and confidence scores.
        timestamp (str): The timestamp of the analysis.

    Returns:
        bool: True if the data was stored successfully, False otherwise.
    """
    try:
        labels_confidences = [
            {'M': {'Name': {'S': label['Name']}, 'Confidence': {'N': str(label['Confidence'])}}}
            for label in labels
        ]

        dynamodb_client.put_item(
            TableName=DYNAMODB,
            Item={
                'filename': {'S': image_name},
                'Labels': {'L': labels_confidences},
                'timestamp': {'S': timestamp},
                'branch': {'S': BRANCH}
            }
        )
        return True
    except ClientError as e:
        print(f"Error storing results for {image_name} in DynamoDB: {e}")
        return False

def image_size_validator(image_path: str, max_size: int = 5242880) -> bool:
    """Checks if the image size is within the allowed limit.

    Args:
        image_path (str): The path of the image.
        max_size (int): The maximum size in bytes.

    Returns:
        bool: True if the image size is valid, False otherwise.
    """
    return os.path.getsize(image_path) <= max_size

# Call the function to execute the image analysis
if __name__ == "__main__":
    """Uploads images to S3, analyzes them with Rekognition, and stores the results in DynamoDB."""
    for image in os.listdir(IMAGES_FOLDER):
        if image.endswith(('.jpg', '.jpeg', '.png')):
            image_path = os.path.join(IMAGES_FOLDER, image)

            # Check if the image size is valid
            if not image_size_validator(image_path):
                print(f"Image {image_path} is too large. Skipping...")
                continue  # Skip the upload if the image is too large

            print(f"\nUploading {image_path} to S3 bucket {BUCKET} with prefix {PREFIX}")

            # Upload the image to S3
            if not upload_image_to_s3(image_path):
                print(f"Failed to upload {image_path} to S3. Skipping analysis.")
                continue  # Skip to the next image if upload fails

            # Analyze the image
            labels, response = analyze_image_using_rekognition(os.path.basename(image))
            if not labels or response is None:
                print(f"Failed to analyze {image_path}. Skipping analysis.")
                continue  # Skip to the next image if analysis fails

            # Print the response from Rekognition
            print(f"\nRekognition response for '{image}':")
            print(f"{'Label':<20} {'Confidence (%)':<15}")
            print("-" * 35)
            for label in labels:
                # Ensure that label has the expected structure
                if 'Name' in label and 'Confidence' in label:
                    print(f"{label['Name']:<20} {label['Confidence']:<15.2f}")

            # Extract the timestamp from the response metadata
            timestamp = response['ResponseMetadata']['HTTPHeaders']['date'] if 'ResponseMetadata' in response else "Unknown"

            # Store the results in DynamoDB
            if store_results_in_dynamodb(os.path.basename(image), labels, timestamp):
                print(f"\nSuccessfully stored results for '{image}' in DynamoDB.")
            else:
                print(f"Failed to store results for '{image}' in DynamoDB.")
        else:
            print(f"Skipping non-image file: {image}")
