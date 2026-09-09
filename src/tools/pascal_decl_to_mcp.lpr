program pascal_decl_to_mcp;

{$mode objfpc}{$H+}

uses
  {$IFDEF UNIX}
  cthreads,
  {$ENDIF}
  {$IFDEF HASAMIGA}
  athreads,
  {$ENDIF}
  Interfaces, // this includes the LCL widgetset
  Forms, pascal_decl_to_mcp_frm, pas_mcp_generator_tool, lingofuse_helper, lingofuse_import, Z.Int128, Z.Json, Z.MemoryStream, Z.Notify, Z.OpCode, Z.Status,
  Z.UnicodeMixedLib, Z.UReplace, Z.HashList.Templet, Z.Parsing, Z.Pascal_Func_Tool, llm_client, llm_tool_frm;

{$R *.res}

begin
  RequireDerivedFormResource:=True;
  Application.Scaled:=True;
  {$PUSH}{$WARN 5044 OFF}
  Application.MainFormOnTaskbar:=True;
  {$POP}
  Application.Initialize;
  Application.CreateForm(Tpascal_decl_to_mcp_form, pascal_decl_to_mcp_form);
  Application.CreateForm(Tllm_tool_form, llm_tool_form);
  Application.Run;
end.

