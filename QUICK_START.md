# QUICK START GUIDE - Excel VBA Sanctions Check

**Time needed to get started: 10-15 minutes**

---

## Step 1: Prepare Your Excel File (2 minutes)

### Create/Update Your Workbook

1. **Open Excel** (Excel 2019, 2021, or Microsoft 365)

2. **Create this structure in Sheet1**:

```
| A                 | B          | C        | D                |
|-------------------|------------|----------|------------------|
| Company Names     | Industry   | Status   | Result           |
| ABC Corporation   |            |          |                  |
| XYZ Limited       |            |          |                  |
| Global Trade Inc  |            |          |                  |
| (add more...)     |            |          |                  |
```

**Column A** = Company names (required)  
**Column B** = Optional info  
**Column C** = Status (will show ✓ when checked)  
**Column D** = Results (will show NO MATCH or MATCH FOUND)

3. **Save as**: `sanctions_workbook.xlsm` (IMPORTANT: `.xlsm` not `.xlsx`)

---

## Step 2: Add the Macro Code (5 minutes)

### Import VBA Code into Excel

1. **Open your Excel file** → Press `Alt + F11` (or Developer tab → Visual Basic)

2. **In the VBA Editor that opens:**
   - Right-click on "VBAProject (sanctions_workbook)" on the left
   - Select: Insert → Module
   - A blank code window opens

3. **Copy the macro:**
   - Open file: `SanctionsCheck_VBA.bas`
   - Select all code (Ctrl+A)
   - Copy (Ctrl+C)

4. **Paste into VBA Editor:**
   - Click in the blank module
   - Paste (Ctrl+V)
   - Save (Ctrl+S)

5. **Close VBA Editor** (click the X button)

---

## Step 3: Enable Macros (2 minutes)

For Excel to allow the macro to run:

### On Windows:
1. **File** → **Options** → **Trust Center**
2. Click **Trust Center Settings**
3. Select **Macro Settings**
4. Choose: **Enable all macros**
5. Click OK

### On Mac:
1. **Excel** menu → **Preferences**
2. **Security & Privacy** → **Trust Center**
3. **Macro Security**
4. Choose: **Enable all macros**

---

## Step 4: Create a Run Button (Optional but Recommended)

Make it super easy for users to run the sanctions check:

1. **Insert** → **Shapes** → **Rectangle**
2. Draw a button on your spreadsheet
3. Right-click → **Edit Text** → Type: "Run Sanctions Check"
4. Right-click → **Assign Macro** → Select `RunSanctionsCheck` → OK
5. Format as you like (colors, font, etc.)

Now users can just click the button!

---

## Step 5: Test with Sample Data (3 minutes)

### Before using with real data:

1. **Add 3-5 sample company names in column A** (rows 2-6):
   - Apple Inc
   - Microsoft Corp
   - Google LLC

2. **Click your macro button** (or: Developer → Macros → RunSanctionsCheck)

3. **Watch as the macro:**
   - Connects to sanctions lists
   - Searches each company
   - Fills in results in column D
   - Shows progress with checkmarks in column C
   - Completes with a message

### Expected Results:
- Column C: Shows ✓ for each company checked
- Column D: Shows "CLEAR - NO MATCH" or "⚠ MATCH FOUND"
- New file created: `sanctions_audit_log_[timestamp].csv`

---

## Step 6: Configure Outlook Notifications (Optional)

To get email when done:

1. **Open config file**: `sanctions_config.json`

2. **Find this section:**
```json
"outlook_configuration": {
  "email_notification_enabled": false,
  "email_recipient": "compliance@company.com"
}
```

3. **Change to:**
```json
"outlook_configuration": {
  "email_notification_enabled": true,
  "email_recipient": "YOUR_EMAIL@company.com"
}
```

4. **Save the file**

Now you'll get an email notification when sanctions check completes!

---

## Step 7: Run on Real Data

### When ready with your company list:

1. **Add all company names** to column A (one per row)
2. **Make sure columns C and D are empty** (or will be overwritten if not)
3. **Click "Run Sanctions Check" button**
4. **Wait for completion** (typical: 5-8 minutes for 100 companies)
5. **Check results** in column D:
   - ✅ CLEAR - NO MATCH = Safe
   - ⚠️ MATCH FOUND = Needs review by compliance
6. **Review the audit log** generated automatically

---

## Understanding the Results

### Column D Results

| Result | Meaning | Action |
|--------|---------|--------|
| CLEAR - NO MATCH | Company is not on sanctions list | Proceed normally |
| ⚠ MATCH FOUND | Company found on a sanctions list | ESCALATE - Review with compliance officer |
| ERROR - CHECK MANUALLY | System couldn't verify | Check manually at: www.ofac.treas.gov or uk-sanctions-list |

---

## Where Are My Results?

### Automatically Generated Files

After running the macro, you'll have:

1. **In the "results" folder:**
   - `sanctions_audit_log_20240424_103045.csv` ← Compliance record
   
2. **In your Excel file:**
   - Results in column D
   - Status checkmarks in column C

### The Audit Log Shows:

```csv
Timestamp,Entity Name,Result,User,Computer
2024-04-24 10:30:45,ABC Corp,CLEAR - NO MATCH,john.smith,DESKTOP-12345
2024-04-24 10:31:12,XYZ Ltd,⚠ MATCH FOUND,john.smith,DESKTOP-12345
```

**This log proves WHO screened WHAT and WHEN** (compliance requirement)

---

## Troubleshooting

### Problem: "Macro not running"

**Solution:**
- Make sure file is saved as `.xlsm` not `.xlsx`
- Check macros are enabled (File → Options → Trust Center)
- Restart Excel

### Problem: "Outlook notification not sending"

**Solution:**
- Make sure Outlook is installed and running
- Check email address in config.json is correct
- Check config.json setting: `"email_notification_enabled": true`

### Problem: "Results showing ERROR - CHECK MANUALLY"

**Solution:**
- Check your internet connection
- Try again in a few minutes (API might be temporary down)
- Manually check at: https://sanctionssearch.ofac.treas.gov/

### Problem: "Audit log not generated"

**Solution:**
- Make sure "results" folder exists (create it if needed)
- Check Windows folder permissions (you need write access)
- Try running as Administrator

---

## Using the Audit Log for Compliance

### Monthly Compliance Report

You can compile all audit logs by:

1. **Collect all** `sanctions_audit_log_*.csv` files
2. **Open Excel** → **Data** tab
3. **New Query** → **From File** → Select all CSV files
4. **Combine & Load** → Creates dashboard
5. **Create Pivot Table** to show:
   - Companies screened: [NUMBER]
   - Matches found: [NUMBER]
   - Dates covered: [START] to [END]
   - Users who performed checks: [NAMES]

This proves your company did **compliance checking**!

---

## Tips for Best Results

1. **Run during off-peak hours** (less server load)
2. **Test with 5-10 companies first** (verify results make sense)
3. **Keep audit logs for 7 years** (regulatory requirement)
4. **Review any "MATCH FOUND" results** with compliance officer
5. **Run weekly** for new vendor screening
6. **Run monthly** for existing counterparties

---

## Sharing with Colleagues

### To send to another user:

1. **Send them:**
   - Your completed `sanctions_workbook.xlsm` file
   - Link to this Quick Start Guide
   - Link to `DEPLOYMENT_GUIDE.md` for more details

2. **They should:**
   - Follow Steps 1-6 above
   - That's it! (No installation needed)

3. **It will work on their desktop immediately!**

---

## When to Use This Tool

### Screen companies when:
- ✅ Adding new vendors/suppliers
- ✅ Onboarding new customers
- ✅ Updating counterparty information
- ✅ Doing quarterly compliance checks
- ✅ Before sending any payments
- ✅ Before signing contracts
- ✅ On board members/officers

### Don't use this for:
- ❌ Individual consumers (use different tool)
- ❌ One-time informal checks (must be logged)
- ❌ Anything not documented (audit trail required)

---

## Getting Help

### Quick Questions:
1. Check Step 1-7 above
2. Check Troubleshooting section
3. Ask your Compliance Officer

### Technical Issues:
1. Check: `DEPLOYMENT_GUIDE.md` - Troubleshooting section
2. Share: Screenshot of error + audit log
3. Contact: compliance-support@company.com

---

## Video Tutorial (If Available)

[Link to video walkthrough would go here]

---

## Next: Learn More

- **Full Documentation**: See `DEPLOYMENT_GUIDE.md`
- **Technical Details**: See `CODE_REVIEW.md`
- **Configuration**: Edit `sanctions_config.json`

---

**You're All Set!** 

🎉 You're ready to start screening companies for sanctions compliance.

**Remember:** The audit log is proof you did the check, so save it!

---

Document Version: 1.0  
Last Updated: April 24, 2024  
Status: READY TO USE ✅
