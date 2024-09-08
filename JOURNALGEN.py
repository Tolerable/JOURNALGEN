import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import requests
from PIL import Image, ImageTk
from io import BytesIO
from datetime import datetime
import os
import json
import threading
import time
import random
import calendar

# Directory to store journal entries and images
SAVE_DIR = "./journal_entries/"
IMAGE_DIR = "./journal_images/"
RETRY_QUEUE = []  # Queue to store entries with failed image generation
SETTINGS_FILE = "./settings.json"

# Placeholder image to keep positions consistent
PLACEHOLDER_IMAGE_PATH = './placeholder.jpg'

# Create save directories if not exist
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)
if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)

# Create the settings file if it doesn't exist
if not os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"always_on_top": False}, f)

# Load or create a placeholder image
def get_placeholder_image():
    if not os.path.exists(PLACEHOLDER_IMAGE_PATH):
        placeholder_image = Image.new('RGB', (150, 84), (200, 200, 200))  # 16:9 grey placeholder
        placeholder_image.save(PLACEHOLDER_IMAGE_PATH)
    return PLACEHOLDER_IMAGE_PATH

# Function to get image from Pollinations.ai with specified dimensions (16:9 aspect ratio) and optional seed
def generate_image_async(entry_id, journal_content, callback):
    def fetch_image():
        try:
            print(f"Generating image for entry: {journal_content}")  # Only show journal content
            seed = random.randint(0, 999999)  # Generate random seed
            response = requests.get(f'https://pollinations.ai/p/{journal_content}?nologo=true&nofeed=true&width=1920&height=1080&enhance=true&seed={seed}')
            if response.status_code == 200:
                image = Image.open(BytesIO(response.content))
                image_path = os.path.join(IMAGE_DIR, f'{entry_id}.jpg')
                image.save(image_path)
                callback(entry_id, image_path)
                print(f"Image successfully generated for entry {entry_id} with seed {seed}")
            else:
                print(f"Failed to generate image for entry {entry_id}. Added to retry queue.")
                RETRY_QUEUE.append((entry_id, journal_content))
        except Exception as e:
            print(f"Error generating image for entry {entry_id}: {e}. Added to retry queue.")
            RETRY_QUEUE.append((entry_id, journal_content))
    threading.Thread(target=fetch_image).start()

# Function to process retry queue (attempts to generate images for previously failed entries)
def process_retry_queue(callback):
    while RETRY_QUEUE:
        entry_id, entry_text = RETRY_QUEUE.pop(0)
        generate_image_async(entry_id, entry_text, callback)

class JournalApp:
    def __init__(self, root):
        self.root = root
        self.root.title("JOURNALGEN")

        # Set window size
        self.root.geometry("900x650")  # Adjust the size as needed

        # Load settings
        self.settings = self.load_settings()
        self.root.attributes('-topmost', self.settings.get("always_on_top", False))

        # Ensure IMAGE_DIR exists
        if not os.path.exists(IMAGE_DIR):
            os.makedirs(IMAGE_DIR)

        # Initialize retry mechanism
        self.retry_queue = []
        self.retry_lock = threading.Lock()

        # Dictionary to store journal entries for each day
        self.entries = {}
        self.current_day = None
        self.current_year = datetime.now().year

        # Main layout
        self.main_frame = ctk.CTkFrame(root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Left-side frame for calendar navigation
        self.left_frame = ctk.CTkFrame(self.main_frame, width=140, fg_color="lightgrey")
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)

        # Month selection dropdown
        self.month_var = tk.StringVar()
        self.month_dropdown = ctk.CTkComboBox(self.left_frame, variable=self.month_var, 
                                              values=list(calendar.month_name)[1:],
                                              command=self.update_calendar,
                                              width=120, height=28)
        self.month_dropdown.set(datetime.now().strftime("%B"))
        self.month_dropdown.pack(pady=10)

        # Year navigation
        self.year_frame = tk.Frame(self.left_frame)
        self.year_frame.pack(pady=3)

        self.prev_year_button = tk.Button(self.year_frame, text="<", command=lambda: self.change_year(-1), font=('Arial', 7), padx=3, pady=1)
        self.prev_year_button.pack(side=tk.LEFT)

        self.year_label = tk.Label(self.year_frame, text=str(self.current_year), font=('Arial', 9))
        self.year_label.pack(side=tk.LEFT, padx=6)

        self.next_year_button = tk.Button(self.year_frame, text=">", command=lambda: self.change_year(1), font=('Arial', 7), padx=3, pady=1)
        self.next_year_button.pack(side=tk.LEFT)

        # Calendar frame
        self.calendar_frame = tk.Frame(self.left_frame)
        self.calendar_frame.pack(fill=tk.BOTH, expand=True)

        # Right-side frame for notebook entries and images
        self.right_frame = ctk.CTkFrame(self.main_frame)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Scrolling area for the entries
        self.entry_canvas = tk.Canvas(self.right_frame)
        self.scrollbar = tk.Scrollbar(self.right_frame, orient="vertical", command=self.entry_canvas.yview)
        self.entry_canvas.configure(yscrollcommand=self.scrollbar.set)

        # Frame inside the canvas to hold the entries
        self.entry_frame = tk.Frame(self.entry_canvas)
        self.entry_canvas.create_window((0, 0), window=self.entry_frame, anchor="nw")
        self.entry_frame.bind("<Configure>", lambda e: self.entry_canvas.configure(scrollregion=self.entry_canvas.bbox("all")))

        # Pack the canvas and scrollbar
        self.entry_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Input bar at the bottom for new journal entries
        self.input_frame = ctk.CTkFrame(self.root)
        self.input_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.input_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Write your journal entry here...", width=850)
        self.input_entry.pack(side=tk.LEFT, padx=20, pady=10)
        self.input_entry.bind("<Return>", self.add_entry)

        # Add "Today" button below the calendar
        self.today_button = tk.Button(self.left_frame, text="Today", command=self.go_to_today, font=('Arial', 10))
        self.today_button.pack(pady=(10, 0))

        # Add a flag to track whether to show the warning
        self.show_post_warning = True

        # Load previously saved entries if they exist
        self.load_all_entries()

        # Initialize the calendar
        self.update_calendar()

        # Load entries for the current day
        current_day = datetime.now().day
        self.load_entries_for_selected_day(current_day)

        # Event bindings
        self.month_dropdown.bind("<<ComboboxSelected>>", self.update_calendar)

        # Start the retry process in the background
        self.retry_thread = threading.Thread(target=self.process_retry_queue, daemon=True)
        self.retry_thread.start()

        # Periodically check for entries without images
        self.root.after(60000, self.check_entries_without_images)  # Check every minute

    def process_retry_queue(self):
        while True:
            with self.retry_lock:
                if self.retry_queue:
                    entry_id, entry_text = self.retry_queue.pop(0)
                    image_path = os.path.join(IMAGE_DIR, f'{entry_id}.jpg')
                    if not os.path.exists(image_path):
                        print(f"Retrying image generation for entry: {entry_id}")
                        self.generate_image_async(entry_id, entry_text, self.update_entry_with_image)
                    else:
                        print(f"Image already exists for entry: {entry_id}")
            time.sleep(5)  # Wait 5 seconds before next retry attempt

    def add_to_retry_queue(self, entry_id, entry_text):
        with self.retry_lock:
            if not any(entry_id == item[0] for item in self.retry_queue):
                self.retry_queue.append((entry_id, entry_text))
                print(f"Added entry {entry_id} to retry queue")
            else:
                print(f"Entry {entry_id} is already in the retry queue")

    def check_entries_without_images(self):
        print("Checking for entries without images...")
        for day, entries in self.entries.items():
            for entry_id, entry_text, image_path in entries:
                if image_path is None or not os.path.exists(image_path):
                    print(f"Found entry without image: {entry_id}")
                    entry_content = entry_text.split('] ', 1)[1] if '] ' in entry_text else entry_text
                    self.add_to_retry_queue(entry_id, entry_content)
                else:
                    print(f"Entry {entry_id} already has an image: {image_path}")
        self.root.after(300000, self.check_entries_without_images)  # Check every 5 minutes

    def update_entry_with_image(self, entry_id, image_path):
        updated = False
        for day, entries in self.entries.items():
            for i, (e_id, e, img) in enumerate(entries):
                if e_id == entry_id:
                    print(f"Updating entry {entry_id} with image: {image_path}")
                    self.entries[day][i] = (e_id, e, image_path)
                    updated = True
                    break
            if updated:
                break
        
        if updated:
            print(f"Successfully updated entry {entry_id} with image.")
            self.save_to_file()
        else:
            print(f"Could not find entry {entry_id} to update with image.")

    def generate_image_async(self, entry_id, journal_content, callback):
        def fetch_image():
            image_path = os.path.join(IMAGE_DIR, f'{entry_id}.jpg')
            try:
                print(f"Generating image for entry: {entry_id}")
                seed = random.randint(0, 999999)
                response = requests.get(f'https://pollinations.ai/p/{journal_content}?nologo=true&nofeed=true&width=1920&height=1080&enhance=true&seed={seed}', timeout=30)
                if response.status_code == 200:
                    image = Image.open(BytesIO(response.content))
                    image.save(image_path)
                    print(f"Image saved to: {image_path}")
                    callback(entry_id, image_path)
                    print(f"Image successfully generated for entry {entry_id} with seed {seed}")
                else:
                    print(f"Failed to generate image for entry {entry_id}. Status code: {response.status_code}")
                    self.add_to_retry_queue(entry_id, journal_content)
            except Exception as e:
                print(f"Error generating image for entry {entry_id}: {e}")
                self.add_to_retry_queue(entry_id, journal_content)
        threading.Thread(target=fetch_image).start()

    # Load settings from file
    def load_settings(self):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)

    # Save settings to file
    def save_settings(self):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(self.settings, f)

    # Toggle Always on Top
    def toggle_always_on_top(self):
        self.settings["always_on_top"] = not self.settings["always_on_top"]
        self.root.attributes('-topmost', self.settings["always_on_top"])
        self.save_settings()

    # Function to check for leap year
    def is_leap_year(self, year):
        return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

    def focus_on_today(self):
        today = datetime.now().day
        self.highlight_day(today)
        self.load_entries_for_selected_day(today)

    def highlight_day(self, day):
        for button in self.calendar_buttons:
            if button["text"] == str(day):
                button.config(bg="lightblue")
            else:
                button.config(bg="SystemButtonFace")

    def change_year(self, delta):
        self.current_year += delta
        self.year_label.config(text=str(self.current_year))
        self.update_calendar()
        self.clear_entries()

    def update_calendar(self, event=None):
        for widget in self.calendar_frame.winfo_children():
            widget.destroy()
        self.calendar_buttons = []

        selected_month = self.month_var.get()
        month_index = list(calendar.month_name)[1:].index(selected_month) + 1

        first_weekday, num_days = calendar.monthrange(self.current_year, month_index)
        first_weekday = (first_weekday + 1) % 7

        # Create labels for weekdays
        weekdays = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
        for i, day in enumerate(weekdays):
            label = tk.Label(self.calendar_frame, text=day, width=2, font=('Arial', 7))
            label.grid(row=0, column=i, sticky="nsew", padx=1, pady=1)

        day_count = 1
        for i in range(6):
            for j in range(7):
                if (i == 0 and j < first_weekday) or (day_count > num_days):
                    label = tk.Label(self.calendar_frame, text="", width=2, height=1)
                    label.grid(row=i+1, column=j, sticky="nsew", padx=1, pady=1)
                else:
                    button = tk.Button(self.calendar_frame, text=str(day_count),
                                       command=lambda d=day_count: self.load_entries_for_selected_day(d),
                                       width=2, height=1, font=('Arial', 7))
                    button.grid(row=i+1, column=j, sticky="nsew", padx=1, pady=1)
                    self.calendar_buttons.append(button)
                    day_count += 1

        current_date = datetime.now()
        if selected_month == current_date.strftime("%B") and self.current_year == current_date.year:
            self.highlight_day(current_date.day)

        self.year_label.config(text=str(self.current_year))
        
        # Update current_day to match the selected month and year
        self.current_day = f"{self.current_year}-{month_index:02d}-01"
        
        # Clear entries and load entries for the first day of the month
        self.clear_entries()
        self.load_entries_for_selected_day(1)

    def clear_entries(self):
        for widget in self.entry_frame.winfo_children():
            widget.destroy()
        self.current_day = None

    def load_all_entries(self):
        self.entries = {}
        for filename in os.listdir(SAVE_DIR):
            if filename.endswith('.json'):
                date = filename[:-5]  # Remove '.json' from the filename
                file_path = os.path.join(SAVE_DIR, filename)
                try:
                    with open(file_path, "r") as f:
                        day_entries = json.load(f)
                    self.entries[date] = day_entries
                    print(f"Loaded {len(day_entries)} entries for {date}")
                except json.JSONDecodeError:
                    print(f"Error loading journal entries for {date}. File may be corrupted.")
        
        # Set current_day to today's date
        self.current_day = datetime.now().strftime("%Y-%m-%d")
        print(f"Current day set to: {self.current_day}")
        
        self.check_entries_without_images()
        
    def load_entries_for_selected_day(self, day):
        selected_month = self.month_var.get()
        month_index = list(calendar.month_name)[1:].index(selected_month) + 1
        selected_date = f"{self.current_year}-{month_index:02d}-{day:02d}"
        
        self.highlight_day(day)
        self.current_day = selected_date
        print(f"Loading entries for: {self.current_day}")

        # Clear previous entries
        for widget in self.entry_frame.winfo_children():
            widget.destroy()

        # Load and display entries for the selected day
        if self.current_day in self.entries:
            for entry_id, entry, image_path in self.entries[self.current_day]:
                self.insert_saved_entry(entry_id, entry, image_path)
            print(f"Loaded {len(self.entries[self.current_day])} entries for {self.current_day}")
        else:
            print(f"No entries found for {self.current_day}")

    def save_to_file(self):
        if self.current_day:
            save_path = os.path.join(SAVE_DIR, f"{self.current_day}.json")
            with open(save_path, "w") as f:
                json.dump(self.entries.get(self.current_day, []), f)

    def add_entry(self, event=None):
        entry_text = self.input_entry.get()
        if entry_text:
            if self.show_post_warning and self.current_day != datetime.now().strftime("%Y-%m-%d"):
                self.show_post_warning_dialog(entry_text)
            else:
                self.process_entry(entry_text)

    def process_entry(self, entry_text):
        self.input_entry.delete(0, tk.END)
        entry_id = datetime.now().strftime("%Y%m%d%H%M%S")
        current_time = datetime.now().strftime("[%I:%M%p] ")
        full_entry = current_time + entry_text
        
        if self.current_day not in self.entries:
            self.entries[self.current_day] = []
        
        self.entries[self.current_day].append((entry_id, full_entry, None))
        self.save_to_file()
        self.insert_saved_entry(entry_id, full_entry, None)
        generate_image_async(entry_id, entry_text, self.update_entry_with_image)

    def go_to_today(self):
        today = datetime.now()
        self.month_var.set(today.strftime("%B"))
        self.current_year = today.year
        self.update_calendar()
        self.load_entries_for_selected_day(today.day)

    def show_post_warning_dialog(self, entry_text):
        dialog = tk.Toplevel(self.root)
        dialog.title("Post Entry")
        dialog.geometry("300x150")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="You're not posting on the current day.\nWhere would you like to post?").pack(pady=10)

        def post_current():
            self.go_to_today()
            self.process_entry(entry_text)
            dialog.destroy()

        def post_selected():
            self.process_entry(entry_text)
            dialog.destroy()

        def post_selected_no_warning():
            self.show_post_warning = False
            self.process_entry(entry_text)
            dialog.destroy()

        tk.Button(dialog, text="Post on Current Day", command=post_current).pack(fill=tk.X, padx=50, pady=5)
        tk.Button(dialog, text="Post on Selected Day", command=post_selected).pack(fill=tk.X, padx=50, pady=5)
        tk.Button(dialog, text="Always Post on Selected Day", command=post_selected_no_warning).pack(fill=tk.X, padx=50, pady=5)

    # Save the current entry with timestamp and asynchronously fetch the image
    def save_entry(self, entry_id, entry_text):
        current_time = datetime.now().strftime("[%I:%M%p] ")  # Generate timestamp
        full_entry = current_time + entry_text
        self.entries.setdefault(self.current_day, []).append((entry_id, full_entry, None))  # Add the entry without an image initially

        # Immediately save the current state to JSON to ensure it persists
        self.save_to_file()

        self.insert_saved_entry(entry_id, full_entry, None)  # Insert text-only entry with placeholder image

        # Asynchronously generate the image and update the entry when available
        generate_image_async(entry_id, entry_text, self.update_entry_with_image)

    # Update an entry with the generated image
    def update_entry_with_image(self, entry_id, image_path):
        # Find the entry in the list and update its image path
        if self.current_day in self.entries:
            for i, (e_id, e, img) in enumerate(self.entries[self.current_day]):
                if e_id == entry_id:
                    print(f"Updating entry {entry_id} with image")
                    self.entries[self.current_day][i] = (e_id, e, image_path)
                    self.replace_existing_entry_with_image(entry_id, e, image_path)
                    break  # Avoid unnecessary iteration
            else:
                print(f"Could not find entry {entry_id} in current day {self.current_day}.")
        else:
            print(f"No entries found for the current day.")

        # Save the updated entries
        self.save_to_file()

    def replace_existing_entry_with_image(self, entry_id, entry, image_path):
        print(f"Replacing image for entry: {entry_id}")
        for widget in self.entry_frame.winfo_children():
            if isinstance(widget, ctk.CTkFrame):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Label) and child.cget("text") == entry:
                        image_label = widget.winfo_children()[0]  # Assuming image is the first child
                        if os.path.exists(image_path):
                            img_thumbnail = Image.open(image_path)
                            img_thumbnail.thumbnail((150, 84))  # 16:9 aspect ratio for thumbnail
                            photo = ImageTk.PhotoImage(img_thumbnail)
                            image_label.config(image=photo)
                            image_label.image = photo  # Keep a reference
                            print(f"Successfully replaced image for entry: {entry_id}")
                            return
        print(f"Could not find widget to update for entry: {entry_id}")

    # Function to insert saved entry with text and image (or placeholder image)
    def insert_saved_entry(self, entry_id, entry, image_path=None):
        entry_frame = ctk.CTkFrame(self.entry_frame, corner_radius=10)
        entry_frame.pack(fill=tk.X, padx=10, pady=5)

        if image_path and os.path.exists(image_path):
            img_thumbnail = Image.open(image_path)
            img_thumbnail.thumbnail((150, 84))  # 16:9 aspect ratio for thumbnail
        else:
            img_thumbnail = Image.open(get_placeholder_image())  # Use placeholder if no image available
        
        photo = ImageTk.PhotoImage(img_thumbnail)
        image_label = tk.Label(entry_frame, image=photo, bd=2, relief="solid")
        image_label.image = photo  # Keep reference to prevent garbage collection
        image_label.pack(side=tk.LEFT, padx=5)

        # Display text aligned to the right of the image
        text_label = tk.Label(entry_frame, text=entry, anchor="w", justify=tk.LEFT, wraplength=500)
        text_label.pack(side=tk.LEFT, padx=10, pady=5)
        
        print(f"Inserted entry: {entry_id} with image path: {image_path}")

        # Bind left-click to show large image
        image_label.bind("<Button-1>", lambda e: self.show_large_image(image_path))
        
        # Bind right-click for context menu
        image_label.bind("<Button-3>", lambda event: self.show_context_menu(event, entry_id, entry_text=entry))
        text_label.bind("<Button-3>", lambda event: self.show_context_menu(event, entry_id, entry_text=entry))

    def show_large_image(self, image_path):
        if image_path and os.path.exists(image_path):
            popup = tk.Toplevel(self.root)
            popup.title("Large Image")
            popup.attributes('-topmost', True)  # Keep the popup on top

            # Calculate 80% of screen size
            screen_width = popup.winfo_screenwidth()
            screen_height = popup.winfo_screenheight()
            popup_width = int(screen_width * 0.8)
            popup_height = int(screen_height * 0.8)

            popup.geometry(f"{popup_width}x{popup_height}")

            img = Image.open(image_path)
            img.thumbnail((popup_width, popup_height))  # Resize image to fit the popup
            photo = ImageTk.PhotoImage(img)

            label = tk.Label(popup, image=photo)
            label.image = photo  # Keep a reference
            label.pack(fill=tk.BOTH, expand=True)

            # Close the popup when clicked
            label.bind("<Button-1>", lambda e: popup.destroy())

    def show_context_menu(self, event, entry_id, entry_text):
        context_menu = tk.Menu(self.root, tearoff=0)
        
        # Extract the content part of the entry (remove timestamp)
        content = entry_text.split('] ', 1)[1] if '] ' in entry_text else entry_text
        
        context_menu.add_command(label="Regen Image", command=lambda: self.retry_image(entry_id, content))
        context_menu.add_command(label="Edit Entry", command=lambda: self.edit_entry(entry_id, entry_text))
        context_menu.add_command(label="Delete Entry", command=lambda: self.delete_entry(entry_id))
        context_menu.post(event.x_root, event.y_root)
    
    def edit_entry(self, entry_id, entry_text):
        # Create a popup window for editing
        edit_popup = tk.Toplevel(self.root)
        edit_popup.title("Edit Entry")
        edit_popup.geometry("500x400")  # Significantly reduced height

        # Extract the timestamp and the actual content
        timestamp, actual_text = entry_text.split(']', 1)
        actual_text = actual_text.strip()

        # Use a Text widget for multi-line editing
        text_box = tk.Text(edit_popup, wrap=tk.WORD, height=8)  # Reduced height
        text_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        text_box.insert(tk.END, actual_text)

        # Function to save changes
        def save_changes():
            new_text = text_box.get("1.0", tk.END).strip()
            full_entry = f"{timestamp}] {new_text}"
            for i, (e_id, _, image_path) in enumerate(self.entries[self.current_day]):
                if e_id == entry_id:
                    self.entries[self.current_day][i] = (e_id, full_entry, image_path)
                    break
            self.save_to_file()
            day = int(self.current_day.split()[1])  # Extract the day number from self.current_day
            self.load_entries_for_selected_day(day)
            edit_popup.destroy()
            self.retry_image(entry_id, new_text)

        # Add a "Save" button
        save_button = tk.Button(edit_popup, text="Save", command=save_changes)
        save_button.pack(pady=(0, 10))

        # Bind Ctrl+S to save changes
        edit_popup.bind("<Control-s>", lambda event: save_changes())

    def delete_entry(self, entry_id):
        # Find and remove the entry from self.entries
        for i, (e_id, _, image_path) in enumerate(self.entries[self.current_day]):
            if e_id == entry_id:
                del self.entries[self.current_day][i]  # Delete the entry
                break
        # Remove the image from the filesystem
        image_file = os.path.join(IMAGE_DIR, f'{entry_id}.jpg')
        if os.path.exists(image_file):
            os.remove(image_file)
        # Refresh the display
        self.load_entries_for_selected_day()
        self.save_to_file()

    def retry_image(self, entry_id, entry_text):
        print(f"Retrying image generation for entry: {entry_id}")
        
        def callback(entry_id, image_path):
            self.update_entry_with_image(entry_id, image_path)
            # Force a complete reload of the current day's entries
            current_day = int(self.current_day.split('-')[2])
            self.load_entries_for_selected_day(current_day)
        
        self.generate_image_async(entry_id, entry_text, callback)
    
# Initialize the app
if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    root = ctk.CTk()
    app = JournalApp(root)
    generate_image_async = lambda entry_id, journal_content, callback: app.generate_image_async(entry_id, journal_content, callback)
    root.mainloop()
