# Podcast Transcription and Topic Segmentation

This is a simple web application that provides a user interface for transcribing and segmenting podcast audio files.

## Features

-   **File Input:** Users can select an audio file from their local computer.
-   **Topic Segmentation:** The application visualizes the podcast transcript segmented by topics.
-   **Transcript Viewer:** The transcript is displayed with topic titles, timestamps, summaries, and keywords.
-   **Clickable Timestamps:** Users can click on a segment to jump to that point in the audio.
-   **Keyword Search:** Users can search for keywords to highlight and navigate relevant segments.

## How to Use

1.  Open the `index.html` file in a web browser.
2.  Click on the "Choose File" button to select an audio file.
3.  Click on the "Process" button to see the (dummy) topic segmentation.
4.  Click on a segment in the transcript viewer to jump to that point in the audio.
5.  Use the search bar to search for keywords in the transcript.

## How to Extend

This application is a frontend prototype. To make it fully functional, you need to implement a backend service for transcription and topic segmentation.

1.  **Backend Service:**
    -   Create a backend service (e.g., using Python with Flask or Node.js with Express) that accepts an audio file.
    -   In the backend, use a Speech-to-Text engine to transcribe the audio.
    -   Implement a topic segmentation algorithm to split the transcript into meaningful segments.
    -   The backend should return a JSON object with the segmented transcript, including topic titles, timestamps, summaries, and keywords.

2.  **Frontend Integration:**
    -   Modify the `script.js` file to send the audio file to your backend service when the "Process" button is clicked. You can use the `fetch` API for this.
    -   On receiving the response from the backend, parse the JSON data and use it to render the segments in the transcript viewer.
    -   Replace the `dummySegments` array with the data received from the backend.

## Consistency Check

The prompt mentions a "Rectification & Verification Task" to check for consistency. To perform this:

1.  After implementing the backend, process the same audio file twice through the entire pipeline.
2.  Compare the transcription output, segment boundaries, and summaries from both runs.
3.  Document any variations.
4.  If the outputs differ significantly, it indicates that some part of your pipeline is non-deterministic. This could be due to the model used for transcription or the algorithm for segmentation. You will need to investigate and apply fixes to make the process deterministic. For example, some models might have settings to control randomness.
