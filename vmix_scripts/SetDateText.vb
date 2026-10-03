' vMix Script (Settings > Scripting > Add, language VB.NET)
' Sets only the date field, e.g. "Mon. 9th Sept. 2026".
' Use it if the Python feeder is not running; it does NOT get draw numbers.
' Change TitleInput / FieldName to match your title.

Dim TitleInput As String = "LottoTitle"
Dim FieldName As String = "Date.Text"

Dim dayNames() As String = {"Sun.", "Mon.", "Tue.", "Wed.", "Thu.", "Fri.", "Sat."}
Dim monthNames() As String = {"Jan.", "Feb.", "Mar.", "Apr.", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."}

Dim d As DateTime = DateTime.Now
Dim n As Integer = d.Day
Dim suffix As String = "th"
If (n Mod 100) < 11 OrElse (n Mod 100) > 13 Then
    Select Case n Mod 10
        Case 1 : suffix = "st"
        Case 2 : suffix = "nd"
        Case 3 : suffix = "rd"
    End Select
End If

Dim text As String = dayNames(CInt(d.DayOfWeek)) & " " & n.ToString() & suffix & " " & monthNames(d.Month - 1) & " " & d.Year.ToString()
API.Function("SetText", Input:=TitleInput, SelectedName:=FieldName, Value:=text)
