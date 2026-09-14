program code_decl_to_mcp;

{$mode objfpc}{$H+}

uses
  mimalloc4p,
  {$IFDEF UNIX}
  cthreads,
  {$ENDIF}
  {$IFDEF HASAMIGA}
  athreads,
  {$ENDIF}
  Interfaces, // this includes the LCL widgetset
  Forms, code_decl_to_mcp_frm, pas_mcp_generator_tool, py_mcp_generator_tool;

{$R *.res}

begin
  RequireDerivedFormResource:=True;
  Application.Scaled:=True;
  {$PUSH}{$WARN 5044 OFF}
  Application.MainFormOnTaskbar:=True;
  {$POP}
  Application.Initialize;
  Application.CreateForm(Tcode_decl_to_mcp_form, code_decl_to_mcp_form);
  Application.Run;
end.

