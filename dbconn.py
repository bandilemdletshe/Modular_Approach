import mysql.connector 
from mysql.connector import Error
from datetime import datetime
import csv
import os

# Function to push data to the database
def push_to_database(Machine_id, CxD_id, Sensor_id, Class, Confidence, Distance, Technical, Emergency,
                     sensor_position="N/A", sensor_health="N/A",
                     detection_datetime="N/A", accelerometer_timestamp="N/A", accelerometer_xyz="N/A",
                     gyroscope_timestamp="N/A", gyroscope_rads="N/A"):

    connection = None
    try:
        connection = mysql.connector.connect(
            host="db-mysql-cas-do-user-18228694-0.k.db.ondigitalocean.com",
            user="doadmin",
            password="AVNS_7urZLsSFI0FeqBhPJ0W",
            database="cas_db",
            port=25060  
        )

        cursor = connection.cursor()

        # Ensure detection_datetime has a valid timestamp
        detection_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if detection_datetime == "N/A" else detection_datetime

        # Convert "N/A" timestamps to NULL (MySQL accepts NULL for datetime)
        accelerometer_timestamp = None if accelerometer_timestamp == "N/A" else accelerometer_timestamp
        gyroscope_timestamp = None if gyroscope_timestamp == "N/A" else gyroscope_timestamp

        # Convert "N/A" to NULL for numeric fields
        gyroscope_rads = None if gyroscope_rads in ["N/A", "", None] else float(gyroscope_rads)

        sql_query = """
        INSERT INTO detections (Machine_id, CxD_id, Sensor_id, Class, Confidence, Distance, Technical, Emergency, 
                                sensor_position, sensor_health, 
                                detection_datetime, accelerometer_timestamp, accelerometer_xyz, 
                                gyroscope_timestamp, gyroscope_rads)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (Machine_id, CxD_id, Sensor_id, Class, Confidence, Distance, Technical, Emergency,
                  sensor_position, sensor_health,
                  detection_datetime, accelerometer_timestamp, accelerometer_xyz,
                  gyroscope_timestamp, gyroscope_rads)

        print(f"Inserting values: {values}")
        cursor.execute(sql_query, values)
        connection.commit()
        print("Data pushed successfully!")
        return True  # Return success status

    except mysql.connector.Error as err:
        print(f"Database Error: {err}")
        return False  # Return failure status

    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

# Function to read CSV file and push new entries
def push_new_entries_to_db(log_file_path="detection_log.csv", last_line_read_path="last_line.txt"):
    try:
        # Try reading the last processed line index
        try:
            with open(last_line_read_path, 'r') as last_line_file:
                last_line_read = int(last_line_file.read().strip())
                print(f"Last line read: {last_line_read}")  # Debug print
        except (FileNotFoundError, ValueError):
            last_line_read = 0  # Start from the first data line (after header)
            print(f"Last line read not found or invalid, starting from line {last_line_read}")  # Debug print

        # Read all lines from CSV
        with open(log_file_path, 'r') as csvfile:
            reader = csv.reader(csvfile)
            lines = list(reader)

        print(f"Total lines in log file: {len(lines)}")  # Debug print

        # If file is empty or only has header
        if len(lines) <= 1:
            print("🔹 No data entries to process.")
            return

        # If we haven't processed any lines yet (last_line_read == 0), skip header
        start_index = 1 if last_line_read == 0 else last_line_read
        new_lines = lines[start_index:]  # Get the lines after the last processed one
        print(f"New lines to process: {len(new_lines)}")  # Debug print

        if not new_lines:
            print("🔹 No new entries to process.")
            return

        # Temporary file to write unprocessed lines
        temp_file_path = log_file_path + ".tmp"
        processed_count = 0

        try:
            with open(temp_file_path, 'w', newline='') as temp_file:
                writer = csv.writer(temp_file)
                
                # Always write the header first
                writer.writerow(lines[0])
                
                for i, line in enumerate(new_lines):
                    if len(line) < 10:  # Ensure we have enough columns
                        print(f"Skipping malformed line: {line}")
                        writer.writerow(line)  # Keep malformed lines in the file
                        continue

                    # Extracting data from the line
                    Machine_id = line[0]
                    CxD_id = line[1]
                    Sensor_id = line[2]
                    Class = line[3]

                    try:
                        Confidence = float(line[4])
                        Distance = float(line[5])
                    except ValueError:
                        print(f"Skipping line due to conversion error: {line}")
                        writer.writerow(line)  # Keep problematic lines in the file
                        continue  

                    Technical = line[6]
                    Emergency = line[7]
                    sensor_position = line[8]
                    sensor_health = line[9]

                    # Extract timestamps if available, otherwise default to "N/A"
                    detection_datetime = line[10] if len(line) > 10 and line[10] != "N/A" else "N/A"
                    accelerometer_timestamp = line[11] if len(line) > 11 and line[11] != "N/A" else "N/A"
                    gyroscope_timestamp = line[12] if len(line) > 12 and line[12] != "N/A" else "N/A"
                    accelerometer_xyz = line[13] if len(line) > 13 else ""
                    gyroscope_rads = line[14] if len(line) > 14 else "N/A"

                    # Push data to the database
                    success = push_to_database(
                        Machine_id, CxD_id, Sensor_id, Class, Confidence, Distance, 
                        Technical, Emergency, sensor_position, sensor_health,
                        detection_datetime, accelerometer_timestamp, accelerometer_xyz, 
                        gyroscope_timestamp, gyroscope_rads
                    )

                    if success:
                        processed_count += 1
                    else:
                        # If database insertion failed, keep the line in the file
                        writer.writerow(line)

                # Write any remaining unprocessed lines
                for line in lines[start_index + processed_count:]:
                    writer.writerow(line)

            # Replace original file with the temporary file
            os.replace(temp_file_path, log_file_path)

            # Update last processed line index
            with open(last_line_read_path, 'w') as last_line_file:
                last_line_file.write(str(start_index + processed_count))

            print(f"Successfully processed and pushed {processed_count} new entries.")

        except Exception as e:
            print(f"Error during file processing: {e}")
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    except Exception as e:
        print(f"Error reading or processing log file: {e}")

# Run the function
if __name__ == "__main__":
    push_new_entries_to_db()
