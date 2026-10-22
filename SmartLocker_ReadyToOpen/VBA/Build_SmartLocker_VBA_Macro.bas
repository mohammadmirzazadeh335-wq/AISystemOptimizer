Attribute VB_Name = "Build_SmartLocker"
' Smart Locker 10-Cell SolidWorks 2025 Macro
' Tools > Macro > Run inside SolidWorks
Option Explicit
Dim swApp As Object
Dim swModel As Object
Dim outPath As String
Sub main()
    Set swApp = Application.SldWorks
    outPath = swApp.GetCurrentMacroPathName
    outPath = Left(outPath, InStrRev(outPath, "\"))
    outPath = outPath & "CAD_From_Macro\"
    MkDir outPath
    MkDir outPath & "Parts"
    MkDir outPath & "Assemblies"
    CreateEquationsFile outPath & "Equations.txt"
    CreateAllParts outPath
    CreateAllAssemblies outPath
    MsgBox "SmartLocker Done! " & outPath, vbInformation
End Sub
Sub CreateEquationsFile(path As String)
    Dim txt As String
    txt = "\"Compartment_Width\"= 400" & vbCrLf & "\"External_Width\"= 950"
    Open path For Output As #1: Print #1, txt: Close #1
End Sub
Sub CreateAllParts(base As String)
    Dim names As Variant: names = Array("Main_Frame","Bottom_Plate","Transfer_Tray")
    Dim i As Integer
    For i=0 To UBound(names)
        Set swModel = swApp.NewDocument(swApp.GetDocumentTemplate(1, "",0,0,0),0,0,0)
        swModel.SaveAs base & "Parts\" & names(i) & ".SLDPRT"
    Next i
End Sub
Sub CreateAllAssemblies(base As String)
    Set swModel = swApp.NewDocument(swApp.GetDocumentTemplate(2, "",0,0,0),0,0,0)
    swModel.SaveAs base & "Assemblies\Main_Assembly.SLDASM"
End Sub