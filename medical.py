#!/usr/bin/env python
#
# ESP-Formstack Data Downloader
# formstack_download.py
#
# Downloads Formstack medical forms to the local directory
# at an approximate speed of 20-25 minutes per thousand.
#

import getpass
import json
import math
import os
import pycurl
import string
import subprocess
import sys
import time
import urllib
import texutil


API_BASE = "https://www.formstack.com/api/v2/"
ESP_WEBSITE = "https://esp.mit.edu/"
#   trailing slashes, please

AFS_PREFIX = "\\\\AFS" if sys.platform.startswith('win32') else "/afs"
AFS_BASE = (AFS_PREFIX, "athena.mit.edu", "activity", "e", "esp", "passwords")
ACCESS_TOKEN_PATH = ("formstack-accounts", "esp-chair", "esp-api-access.txt")
ENCRYPTION_KEY_PATH = ("formstack-encryption", "%s-medical", "%s.txt")

# NOTE: if you change the form, make sure to change the LaTeX template as well!
REQUIRED_FIELDS = ["esp_username", "esp_id_number", "full_legal_name",
                   "birthdate", "cell_phone_number", "home_address",
                   "parentguardian_no_1", "parentguardian_no_2",
                   "emergency_contact",
                   "chronic_medical_conditions_requiring_ongoing_care",
                   "allergies_animals_latex_food_meds_other",
                   "prescription_medicines_used_regularly_or_needed_on_occasion",
                   "any_other_health_issues_that_mit_andor_esp_should_be_aware_of",
                   "date_of_last_tetanus_booster", "physician_name",
                   "physician_phone", "name_of_health_insurance_company",
                   "primary_subscriber", "policy_number"]


def full_download():
    try:
        config = initialize()
        choose_new_folder(config)
        discover_token(config)
        choose_form(config)
        discover_enckey(config)
        load_fields(config)
        
        all_submissions = list_submissions(config)
        total = len(all_submissions)
        for id in all_submissions:
            process_submission(config, id)
            print "Downloaded %s/%s" % (len(config.submissions), total)
        write_index(config)
        save_state(config)
        finalize(config)
    except:
        exception_handler(config)

def incremental_download():
    try:
        config = initialize()
        choose_existing_folder(config)
        discover_token(config)
        discover_enckey(config)

        all_submissions = list_submissions(config)
        total = len(all_submissions)
        print "Already Downloaded: " + str(len(config.submissions))
        for id in all_submissions:
            if id not in config.submissions:
                process_submission(config, id)
                print "Downloaded %s/%s" % (len(config.submissions), total)
        write_index(config)
        save_state(config)
        finalize(config)
    except:
        exception_handler(config)

def check():
    try:
        config = initialize()
        choose_existing_folder(config)
        
        username = raw_input("ESP Website Username: ")
        password = getpass.getpass("ESP Website Password: ")
        print ""
        
        endpoint = ESP_WEBSITE + "medicalsyncapi"
        result = make_request(endpoint, {"username": username,
                                         "password": password,
                                         "program": config.program})
        result = json.loads(result)
        
        if not "submitted" in result or not "bypass" in result:
            raise Exception("Invalid response from ESP website")
        
        submitted = result['submitted']
        bypass = result['bypass']
        
        missing = list()
        for id, name in submitted.iteritems():
            if str(id) not in config.userlines:
                missing.append(name)
        
        missing.sort()
        print "Students with a Missing Medical Form (%s):" \
              % len(missing)
        for name in missing:
            print name
        
        print ""
        print "Students with a Bypass (%s):" % len(bypass)
        for name in sorted(bypass.values()):
            print name
        
        print ""
        print "Check Complete!"
    except:
        exception_handler(config, False)

def initialize():
    # Print header and check environment
    print ""
    print "Formstack Medical Form Downloader"
    print "---------------------------------"
    print ""
    
    # Check for certificate bundle
    if not os.path.exists("cacert.pem"):
        print "Missing cacert.pem in current directory."
        print "Please download from http://curl.haxx.se/ca/cacert.pem"
        raise Exception("Missing cacert.pem")
    
    # Check for LaTeX template
    if not os.path.exists("template.tex"):
        print "Missing template.tex in current directory."
        raise Exception("Missing template.tex")
    
    # Create config
    class Config:
        oauth_token = None
        form = None
        program = None
        folder = None
        enckey = None
        shortnames = None
        userlines = dict()
        submissions = list()
        SAVE_FIELDS = ["form", "program", "shortnames", "userlines",
                       "submissions"]
    config = Config()
    
    # Load LaTeX template as config.template
    latex_file = open("template.tex", "r")
    config.template = latex_file.read()
    latex_file.close()
    
    return config

def choose_new_folder(config):
    # Prompt the user to select a safe directory to store the downloaded medical
    # forms. This path is stored in config.folder.
    print "Please create a directory to store the downloaded medical forms."
    print "This directory should be encrypted if possible and NOT backed up."
    print ""
    config.folder = raw_input("Path: ")
    if not os.path.isdir(config.folder):
        raise Exception("The given path does not point to a valid directory.")
    if len(os.listdir(config.folder)) != 0:
        raise Exception("The specified directory is not empty.")
    print ""

def choose_existing_folder(config):
    # Prompts the user to select a directory with existing medical forms. The
    # path is stored in config.folder, and JSON values are loaded from
    # the config.json file and stored in config.
    print "Please select an existing data directory to load."
    print ""
    config.folder = raw_input("Path: ")
    if not os.path.isdir(config.folder):
        raise Exception("The given path does not point to a valid directory.")
    try:
        json_path = os.path.join(config.folder, "config.json")
        f = open(json_path, "r")
        d = json.load(f)
        for k, v in d.iteritems():
            setattr(config, k, v)
    except IOError:
        raise Exception("The specified directory could not be loaded.")
    
    print ""
    print "Program Name: " + config.program
    print ""
    
def discover_token(config):
    # Collect Formstack connection information, reading it out of AFS if
    # possible, or else by prompting the user to look it up. The token is
    # stored in config.oauth_token.
    try:
        afs_path = os.path.join(AFS_PREFIX, *(AFS_BASE + ACCESS_TOKEN_PATH))
        f = open(afs_path, "r")
        config.oauth_token = f.read().strip()
    except IOError:
        print "Could not read access token out of AFS"
        print ""
        config.oauth_token = raw_input("Access Token (see bit.ly/uoT3B2): ")
        print ""

def choose_form(config):
    # Prompt the user to select a form, listing only those in the "Medical"
    # folder if one exists.
    #
    # The form object is stored in config.form; the autodetected program name
    # is stored in config.program, and the path to the folder on disk is stored
    # in config.folder.
    print "Select which form to download"
    forms_list = api_query("form",
                           {"folders": "1", "oauth_token": config.oauth_token})
    forms = list()
    if "Medical" in forms_list["forms"]:
        forms.extend(forms_list["forms"]["Medical"])
        # list of all forms in the Medical folder
        print "(listing all forms in the Medical folder)"
    else:
        for folder in forms_list["forms"]:
            forms.extend(forms_list["forms"][folder])
        print "(listing all forms}"
    
    for i in range(len(forms)):
        print str(i) + " " + forms[i]["name"]
    form_no = raw_input("Form Number: ")
    config.form = forms[int(form_no)]
    print ""

    # Parse program name from form title
    config.program = string.join(config.form["name"].split(" ")[:-1])
    print "Detected program name: " + config.program
    print ""

def discover_enckey(config):
    # Collect the form's encryption key, first by looking in AFS (the path is
    # calculated based on the form name), then by prompting the user. The key
    # is stored in config.enckey.
    afs_path = os.path.join(AFS_PREFIX, *(AFS_BASE + ENCRYPTION_KEY_PATH))
    chunks = config.program.lower().split(" ")
        # e.g. ["spark", "2014"] or ["summer", "hssp", "2013"]
    if len(chunks) == 2:
        prog = chunks[0]
        year = chunks[1]
        afs_path = afs_path % (prog, year)
    elif len(chunks) == 3:
        prog = chunks[1]
        semester = chunks[0] + "-" + chunks[2]
        afs_path = afs_path % (prog, semester)
    else:
        afs_path = None
    
    try:
        if afs_path is None:
            raise IOError()
        f = open(afs_path, "r")
        config.enckey = f.read().strip()
    except IOError:
        print "Could not read encryption password out of AFS"
        print ""
        config.enckey = raw_input("Encryption Password: ")
        print ""

def load_fields(config):
    # Verify that all REQUIRED_FIELDS exists in the selected form, and put them
    # in config.shortnames, a dict of shortname (e.g. policy_number, etc.)
    # => list of ids
    config.shortnames = dict()
    field_list = api_query("form/" + config.form["id"] + "/field",
                           {"oauth_token": config.oauth_token,
                            "encryption_password": config.enckey})
    
    for field in field_list:
        if field["name"] == "":
            continue

        if field["name"] in config.shortnames:
            config.shortnames[field["name"]].append(field["id"])
        else:
            config.shortnames[field["name"]] = [field["id"]]

    for field in REQUIRED_FIELDS:
        if field not in config.shortnames:
            raise Exception("No field found with name '" + field + "'")

def list_submissions(config):
    # Returns a list of all medical form submissions as a list of string IDs
    # Get List of All Medical Form Submissions (in pages of 100)
    submission_ids = list()
    for n in range(1, int(math.ceil(int(config.form["submissions"]) / 100.0) + 1)):
        submission_list = api_query("form/" + config.form["id"] + "/submission",
                                    {"page": str(n), "per_page": "100",
                                     "sort": "ASC", "oauth_token": config.oauth_token,
                                     "encryption_password": config.enckey})
        
        for submission in submission_list["submissions"]:
            submission_ids.append(submission["id"])
    
    print "Total Medical Forms: " + str(len(submission_ids))
    return submission_ids

def process_submission(config, id):
    # Downloads the submission with the specified ID and creates the PDF of
    # their medical form. Note that in order for version numbers to work
    # properly, submissions should be processed in oldest-to-newest order.
    # config.userlines is used to track medical forms and verisons,
    # config.submissions is used to track submission IDs.
    details = api_query("submission/" + str(id),
                        {"oauth_token": config.oauth_token,
                         "encryption_password": config.enckey})
    
    values = dict()
    values_escaped = dict()
    for v in config.shortnames:
        values[v] = search_details_list(details, config.shortnames[v])
        values_escaped[v] = texutil.latex_escape(values[v])
    
    esp_id = int(values["esp_id_number"])
    if esp_id not in config.userlines:
        config.userlines[esp_id] = dict()
        version = 1
    else:
        version = config.userlines[esp_id]["next"]
    config.userlines[esp_id]["next"] = version + 1
    
    userline = values["esp_id_number"] + " - " + \
               values["full_legal_name"] + " - " + values["esp_username"]
    userline = userline.encode("ascii", "ignore")
        # TODO: this is sub-optimal because it removes weird characters

    filename = sanitize_filename(userline + " (v" + str(version) + ")")
    config.userlines[esp_id][str(version)] = filename

    values_escaped["version"] = str(version)
    values_escaped["formatted_date"] = \
        time.strftime("%B %d, %Y", time.strptime(details["timestamp"], "%Y-%m-%d %H:%M:%S"))

    interpolated_template = config.template
    for ve in values_escaped:
        interpolated_template = \
                              interpolated_template.replace(
                                  "[[" + ve + "]]", values_escaped[ve])
    
    report_tex = open(os.path.join(config.folder, filename + ".tex"), "w")
    report_tex.write(interpolated_template.encode("utf8", "ignore"))
        # TODO: this is sub-optimal because it removes weird characters
    report_tex.close()
    
    subprocess.call(["pdflatex", filename + ".tex",
                     "-output-directory=" + config.folder])
    config.submissions.append(id)
    
def write_index(config):
    # Create index file listing file names
    index = open(os.path.join(config.folder, "000 - index.txt"), "w")
    index.write(config.program + "\n")
    index.write("MIT Educational Studies Program\n")
    index.write("esp@mit.edu  |  (617) 253-4882\n")
    index.write("Last Updated: " + time.asctime(time.localtime(time.time())) + "\n")
    index.write("\n")
    
    for esp_id in sorted(config.userlines.iterkeys()):
        version = 1
        while str(version) in config.userlines[esp_id]:
            index.write(config.userlines[esp_id][str(version)] + "\n")
            version += 1
    index.close()

def save_state(config):
    # Write most of the contents of config to the file config.json
    json_path = os.path.join(config.folder, "config.json")
    f = open(json_path, "w")
    d = dict()
    for key in config.SAVE_FIELDS:
        d[key] = getattr(config, key)
    json.dump(d, f)

def finalize(config):
    # Clean up auxiliary files
    for f in os.listdir(config.folder):
        if f.endswith(".tex") or f.endswith(".log") or f.endswith(".aux"):
            os.remove(os.path.join(config.folder, f))

    # Test for successful PDF creation
    contents = os.listdir(config.folder)
    for esp_id, versions in config.userlines.iteritems():
        version = 1
        while version in versions:
            filename = versions[version] + ".pdf"
            if filename not in contents:
                raise Exception("Missing file: " + filename)
            version += 1
    print ""
    print "Done! Enjoy!"


def api_query(endpoint, parameters):
    url = API_BASE + endpoint + "?" + urllib.urlencode(parameters)
    result = make_request(url)
    return json.loads(result)

def make_request(url, post=dict()):
    # pycurl code thanks to [bit.ly/StT2y8]
    class Response(object):
        """ utility class to collect the response """
        def __init__(self):
            self.chunks = []
        def callback(self, chunk):
            self.chunks.append(chunk)
        def content(self):
            return "".join(self.chunks)
    
    res = Response()
    curl = pycurl.Curl()
    curl.setopt(curl.URL, str(url))
    curl.setopt(curl.WRITEFUNCTION, res.callback)
    curl.setopt(curl.CAINFO, "cacert.pem")

    if len(post) != 0:
        curl.setopt(curl.POSTFIELDS, urllib.urlencode(post))

    try:
        curl.perform()
    except pycurl.error:
        time.sleep(5)
        print "Connection failed; retrying"
        return make_request(url, post)
    
    http_code = curl.getinfo(curl.HTTP_CODE)
    result = res.content()

    if http_code != 200:
        raise Exception("HTTP ERROR " + str(http_code) + "\n" + result)
    if result == "Sorry, but an error has occurred":
        raise Exception("API ERROR: Sorry, but an error has occurred" +
                        " (invalid endpoint?)")
    return result

def search_details(details, field_id):
    for item in details["data"]:
        if item["field"] == str(field_id):
            if item["value"] in [None, True, False]:
                return ""
            else:
                return item["value"]
    raise KeyError("Field not found in details: " + field_id)

def sanitize_filename(filename):
    # thanks to [http://stackoverflow.com/questions/295135]
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    return "".join(c for c in filename if c in valid_chars)

def search_details_list(details, field_ids):
    # Handle multiple fields with the same ID, e.g. Tetanus Booster and
    # I Have Never Had a Tetanus Booster
    value = None
    for field_id in field_ids:
        try:
            value = search_details(details, field_id)
            if len(value) > 0:
                return value
        except KeyError:
            pass
    
    if value is not None:
        return value
    raise KeyError("Field not found in details: " + field_id)

def exception_handler(config, do_save_state=True):
    exc = sys.exc_info()[1]
    print ""
    print ""
    msg = "Exiting due to " + exc.__class__().__repr__()[:-2]
    if exc.message is not "":
        msg += ": " + exc.message
    print msg
    if len(config.submissions) != 0 and do_save_state:
        save_state(config)
        print ""
        print "  State has been saved, but download is incomplete."
        print "  Recover by running 'medical.py update'"
    sys.exit(1)

def usage():
    print """Usage: medical.py option
  Options:
    complete: download complete medical archive
    update:   update a medical archive
    check:    cross-check against website registrations"""

if __name__ == "__main__":
    if len(sys.argv) == 1:
        usage()
    elif sys.argv[1] == "complete":
        full_download()
    elif sys.argv[1] == "update":
        incremental_download()
    elif sys.argv[1] == "check":
        check()
    else:
        usage()
