# T1. Simple Rescheduling

: 다른 담당자와 협상할 필요가 없는 일정 변경.

[원본 일정 보드](/demos/m4_t1_rescheduling/board)

1. 변경 요청
    
    Dev → Polish 작업을 하루 뒤로 이동하고 싶습니다. Bug Fix와 Core X 일정은 그대로 유지하고 싶습니다.
    
2. 협의 참여 에이전트
    
    없음. Dev Agent 단독 처리.
    
3. 협상에 관여하는 담당자별 제약 및 위임 규칙
    
    Dev : Polish는 P3. 11/25까지 완료하면 되며 본인 작업을 1영업일 이내 이동 가능. 11/23 작업 총량은 8h 이하.
    
    QA : Final Test는 Core X와 Bug Fix 완료 후 진행. Polish는 필수 테스트 선행 작업이 아님.
    
4. 기대하는 협상안(예시)
    
    Polish를 11/23 이동. 협상이 필요없다는 것을 AI 자동 확인. contraint 확인 후 단순 일정 조정.
    
5. AI prompt evaluation
- 불필요한 협상 방지 : 다른 작업에 영향이 없음을 확인하고 GD, Art, QA에게 연락하지 않았는가.
- 위임 규칙 준수 : Dev의 1 영업일 이동 권한을 정확히 적용하는가
- 일정 검증 : 11/23의 가용 8h 안에 polish 6h가 들어가는지 확인하는가
- 정확한 변경 : polish만 이동하고 Bug fix 및 QA 일정은 유지하는가

