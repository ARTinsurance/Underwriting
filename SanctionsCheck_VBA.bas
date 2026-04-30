' ============================================================
' SANCTIONS CHECK AUTOMATION - Excel VBA Macro
' ============================================================
' Objective: Cross-platform sanctions checking without Python/external tools
' Improvements:
' - Removes Internet Explorer dependency
' - Uses HTTP API / search endpoints for US, UK, EU lists
' - Adds real-time parsing and retry logic
' - Writes audit trail to a dedicated worksheet and CSV
' - Supports different user computers via relative workbook paths
' - Includes configurable wait/retry behavior
' ============================================================

Option Explicit

Const MAX_RETRIES As Integer = 3
Const REQUEST_TIMEOUT_MS As Long = 30000
Const WAIT_SECONDS As Integer = 1
Const LOG_SHEET_NAME As String = "SanctionsAudit"

' Entry point for daily sanctions screening
Sub RunSanctionsCheck()
    On Error GoTo ErrorHandler

    Dim wb As Workbook
    Dim ws As Worksheet
    Dim auditWs As Worksheet
    Dim companyNames As Variant
    Dim i As Long
    Dim total As Long
    Dim startTime As Double
    Dim elapsedTime As Double

    Application.ScreenUpdating = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual
    Application.StatusBar = "Preparing sanctions check..."

    Set wb = ThisWorkbook
    Set ws = GetInputWorksheet(wb)
    If ws Is Nothing Then
        Err.Raise vbObjectError + 1, , "Input worksheet not found. Ensure the sheet with company names exists."
    End If

    Set auditWs = CreateOrResetAuditSheet(wb)
    InitializeAuditHeaders auditWs

    companyNames = ReadCompanyNames(ws)
    If Not IsArray(companyNames) Then
        MsgBox "No company names found in column A.", vbExclamation, "Sanctions Check"
        GoTo Cleanup
    End If

    If UBound(companyNames) < LBound(companyNames) Then
        MsgBox "No company names found in column A.", vbExclamation, "Sanctions Check"
        GoTo Cleanup
    End If

    total = UBound(companyNames)

    startTime = Timer

    For i = 1 To total
        Dim companyName As String
        Dim result As String
        Dim statusMark As String

        companyName = Trim(companyNames(i))
        If Len(companyName) > 0 Then
            ws.Cells(i + 1, 3).Value = "Processing..."
            Application.StatusBar = "Checking " & companyName & " (" & i & " of " & total & ")"

            result = PerformSanctionsCheck(companyName)
            statusMark = IIf(InStr(result, "MATCH") > 0, "⚠", "✓")

            ws.Cells(i + 1, 4).Value = result
            ws.Cells(i + 1, 3).Value = statusMark

            AppendAuditEntry auditWs, companyName, result

            DoEvents
            Application.Wait Now + TimeSerial(0, 0, WAIT_SECONDS)
        End If
    Next i

    elapsedTime = Timer - startTime
    ExportAuditLogCSV wb, auditWs

    MsgBox "Sanctions check completed!" & vbCrLf & _
           "Total entities: " & total & vbCrLf & _
           "Elapsed time: " & Format(elapsedTime / 60, "0.00") & " minutes", vbInformation, "Sanctions Check"

Cleanup:
    Application.StatusBar = False
    Application.ScreenUpdating = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
    Exit Sub

ErrorHandler:
    MsgBox "Error: " & Err.Description, vbCritical, "Sanctions Check"
    Resume Cleanup
End Sub

' Select input worksheet by name or active sheet
Function GetInputWorksheet(wb As Workbook) As Worksheet
    On Error Resume Next
    Set GetInputWorksheet = wb.Worksheets("Sheet1")
    If GetInputWorksheet Is Nothing Then
        Set GetInputWorksheet = wb.ActiveSheet
    End If
    On Error GoTo 0
End Function

' Read company names from column A and return a 1-based array
Function ReadCompanyNames(ws As Worksheet) As Variant
    Dim lastRow As Long
    Dim i As Long
    Dim coll As Collection
    Dim value As String
    Dim names() As String

    Set coll = New Collection
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row

    For i = 2 To lastRow
        value = Trim(CStr(ws.Cells(i, 1).Value))
        If Len(value) > 0 Then coll.Add value
    Next i

    If coll.Count = 0 Then
        ReadCompanyNames = Array()
        Exit Function
    Else
        ReDim names(1 To coll.Count)
        For i = 1 To coll.Count
            names(i) = coll(i)
        Next i
    End If

    ReadCompanyNames = names
End Function

' Perform the combined sanctions check for US, UK, EU lists
Function PerformSanctionsCheck(companyName As String) As String
    Dim ofacResult As String
    Dim ukResult As String
    Dim euResult As String
    Dim result As String

    ofacResult = SearchOFAC(companyName)
    ukResult = SearchUKSanctions(companyName)
    euResult = SearchEUSanctions(companyName)

    If ofacResult <> "CLEAR" Or ukResult <> "CLEAR" Or euResult <> "CLEAR" Then
        result = "⚠ MATCH FOUND" & vbCrLf & _
                 "OFAC: " & ofacResult & vbCrLf & _
                 "UK: " & ukResult & vbCrLf & _
                 "EU: " & euResult
    Else
        result = "CLEAR - NO MATCH"
    End If

    PerformSanctionsCheck = result
End Function

' Search OFAC using the public sanctionsearch endpoint
Function SearchOFAC(companyName As String) As String
    Dim url As String
    Dim response As String
    Dim retries As Integer

    url = "https://sanctionssearch.ofac.treas.gov/api/sanctionsearch?query=" & URLEncode(companyName)
    For retries = 1 To MAX_RETRIES
        response = GetHttpResponse(url)
        If Len(response) = 0 Then
            If retries < MAX_RETRIES Then
                Application.Wait Now + TimeValue("00:00:02")
            Else
                SearchOFAC = "CHECK_ERROR"
                Exit Function
            End If
        Else
            If InStr(response, """total""":0") > 0 Then
                SearchOFAC = "CLEAR"
            ElseIf InStr(response, """total""":") > 0 Then
                SearchOFAC = "MATCH FOUND"
            Else
                SearchOFAC = "CHECK_ERROR"
            End If
            Exit Function
        End If
    Next retries
End Function

' Search UK sanctions via gov.uk search page results
Function SearchUKSanctions(companyName As String) As String
    Dim url As String
    Dim response As String

    url = "https://www.gov.uk/search/all?keywords=" & URLEncode(companyName) & "&order=relevance"
    response = GetHttpResponse(url)

    If Len(response) = 0 Then
        SearchUKSanctions = "CHECK_ERROR"
        Exit Function
    End If

    If InStr(UCase(response), UCase(companyName)) > 0 Then
        SearchUKSanctions = "MATCH FOUND"
    Else
        SearchUKSanctions = "CLEAR"
    End If
End Function

' Search EU sanctions via the EU open data search endpoint
Function SearchEUSanctions(companyName As String) As String
    Dim url As String
    Dim response As String

    url = "https://data.europa.eu/search?query=" & URLEncode(companyName)
    response = GetHttpResponse(url)

    If Len(response) = 0 Then
        SearchEUSanctions = "CHECK_ERROR"
        Exit Function
    End If

    If InStr(UCase(response), UCase(companyName)) > 0 Then
        SearchEUSanctions = "MATCH FOUND"
    Else
        SearchEUSanctions = "CLEAR"
    End If
End Function

' Get HTTP response from a URL with timeout control and JSON headers
Function GetHttpResponse(url As String) As String
    Dim xmlhttp As Object
    Dim responseText As String
    Dim statusCode As Long

    On Error GoTo RequestError
    Set xmlhttp = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    xmlhttp.setTimeouts REQUEST_TIMEOUT_MS, REQUEST_TIMEOUT_MS, REQUEST_TIMEOUT_MS, REQUEST_TIMEOUT_MS
    xmlhttp.Open "GET", url, False
    xmlhttp.setRequestHeader "Accept", "application/json, text/html"
    xmlhttp.setRequestHeader "User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    xmlhttp.Send

    statusCode = xmlhttp.Status
    If statusCode = 200 Then
        responseText = xmlhttp.responseText
    Else
        responseText = ""
    End If

    GetHttpResponse = responseText
    Exit Function

RequestError:
    GetHttpResponse = ""
    Err.Clear
End Function

' Add or recreate the audit worksheet used for reporting
Function CreateOrResetAuditSheet(wb As Workbook) As Worksheet
    Dim ws As Worksheet
    Dim oldDisplayAlerts As Boolean

    oldDisplayAlerts = Application.DisplayAlerts
    On Error Resume Next
    Set ws = wb.Worksheets(LOG_SHEET_NAME)
    If Not ws Is Nothing Then
        Application.DisplayAlerts = False
        ws.Delete
        Application.DisplayAlerts = oldDisplayAlerts
        Set ws = Nothing
    End If
    On Error GoTo 0

    Set CreateOrResetAuditSheet = wb.Worksheets.Add(Before:=wb.Worksheets(1))
    CreateOrResetAuditSheet.Name = LOG_SHEET_NAME
End Function

' Write header row for the audit worksheet
Sub InitializeAuditHeaders(ws As Worksheet)
    With ws
        .Cells.Clear
        .Range("A1:F1").Value = Array("Timestamp", "Entity", "Search Result", "User", "Computer", "Source")
        .Rows(1).Font.Bold = True
        .Columns("A:F").AutoFit
    End With
End Sub

' Append a single audit entry to the audit worksheet
Sub AppendAuditEntry(ws As Worksheet, companyName As String, result As String)
    Dim nextRow As Long
    nextRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row + 1

    ws.Cells(nextRow, 1).Value = Format(Now(), "yyyy-mm-dd hh:mm:ss")
    ws.Cells(nextRow, 2).Value = companyName
    ws.Cells(nextRow, 3).Value = result
    ws.Cells(nextRow, 4).Value = Environ("USERNAME")
    ws.Cells(nextRow, 5).Value = Environ("COMPUTERNAME")
    ws.Cells(nextRow, 6).Value = "US/UK/EU"
End Sub

' Export the audit worksheet contents to a CSV file in the workbook folder
Sub ExportAuditLogCSV(wb As Workbook, auditWs As Worksheet)
    Dim fso As Object
    Dim csvFile As Object
    Dim logPath As String
    Dim i As Long
    Dim rowCount As Long
    Dim lineText As String

    On Error GoTo ExportError

    Set fso = CreateObject("Scripting.FileSystemObject")
    logPath = wb.Path & "\sanctions_audit_log_" & Format(Now(), "yyyymmdd_hhmmss") & ".csv"
    Set csvFile = fso.CreateTextFile(logPath, True, True)

    rowCount = auditWs.Cells(auditWs.Rows.Count, 1).End(xlUp).Row
    For i = 1 To rowCount
        lineText = QuoteCsv(CStr(auditWs.Cells(i, 1).Text)) & "," & _
                   QuoteCsv(CStr(auditWs.Cells(i, 2).Text)) & "," & _
                   QuoteCsv(CStr(auditWs.Cells(i, 3).Text)) & "," & _
                   QuoteCsv(CStr(auditWs.Cells(i, 4).Text)) & "," & _
                   QuoteCsv(CStr(auditWs.Cells(i, 5).Text)) & "," & _
                   QuoteCsv(CStr(auditWs.Cells(i, 6).Text))
        csvFile.WriteLine lineText
    Next i

    csvFile.Close
    MsgBox "Audit log exported to: " & logPath, vbInformation, "Sanctions Check"
    Exit Sub

ExportError:
    MsgBox "Failed to export audit log: " & Err.Description, vbCritical, "Sanctions Check"
    Err.Clear
End Sub

' URL encode a string for HTTP queries
Function URLEncode(str As String) As String
    Dim i As Long
    Dim ch As String
    Dim code As Long
    Dim result As String

    result = ""
    For i = 1 To Len(str)
        ch = Mid$(str, i, 1)
        code = Asc(ch)
        Select Case code
            Case 48 To 57, 65 To 90, 97 To 122, 45, 46, 95, 126
                result = result & ch
            Case 32
                result = result & "%20"
            Case Else
                result = result & "%" & Hex(code)
        End Select
    Next i

    URLEncode = result
End Function

' Quote fields for CSV output and escape internal quotes
Function QuoteCsv(value As String) As String
    value = Replace(value, """", """""")
    QuoteCsv = """" & value & """"
End Function
